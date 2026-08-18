"""Owned HTTP egress for non-data external sinks.

This gateway is intentionally separate from the Framework/Harvester data
gateways.  It is for configured notification, observability, and optional
LLM sinks only; callers select an endpoint identifier and never provide a
request URL at send time.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping
from urllib.parse import urlparse

import httpcore
import httpx

_SINK_REDACTIONS = (
    (re.compile(r"https?://[^\s\"']+", re.IGNORECASE), "[redacted-url]"),
    (re.compile(r"\?[^\s\"']*=[^\s\"']+", re.IGNORECASE), "?[redacted-query]"),
    (re.compile(r"\bbearer\s+[^\s,;]+", re.IGNORECASE), "Bearer [redacted-credential]"),
    (
        re.compile(
            r"\b(?:api[_-]?key|token|secret|password|authorization|dsn)\b\s*[:=]\s*[^\s,;]+",
            re.IGNORECASE,
        ),
        "[redacted-credential]",
    ),
)


class ExternalGatewayError(RuntimeError):
    """Base error whose message never contains endpoint or credential data."""


class ExternalGatewayPolicyError(ExternalGatewayError):
    """Raised when configured external egress violates its policy."""


class ExternalGatewayResponseTooLarge(ExternalGatewayPolicyError):
    """Raised when a sink response exceeds the configured byte budget."""


@dataclass(frozen=True)
class ExternalEndpointSpec:
    """A code-owned, configured endpoint for one non-data sink."""

    endpoint_id: str
    url: str
    allowed_hosts: frozenset[str]

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme.casefold() != "https" or not host:
            raise ExternalGatewayPolicyError("external endpoint must use HTTPS")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ExternalGatewayPolicyError("external endpoint contains forbidden URL parts")
        if host not in {item.casefold() for item in self.allowed_hosts}:
            raise ExternalGatewayPolicyError("external endpoint host is not allowlisted")
        if not self.endpoint_id.strip():
            raise ExternalGatewayPolicyError("external endpoint identifier is empty")


@dataclass(frozen=True)
class ExternalGatewayResponse:
    """Bounded response detached from the live HTTPX client."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes


def _is_forbidden_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def redact_sink_text(value: object) -> str:
    """Remove URLs, queries, and labelled credentials from sink text."""
    text = str(value)
    for pattern, replacement in _SINK_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def resolve_external_url(url: str) -> tuple[str, ...]:
    """Validate a configured HTTPS endpoint and capture one public DNS snapshot."""
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme.casefold() != "https" or not host:
        raise ExternalGatewayPolicyError("external endpoint must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ExternalGatewayPolicyError("external endpoint contains forbidden URL parts")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if _is_forbidden_ip(address):
            raise ExternalGatewayPolicyError("external endpoint targets a forbidden IP")
        return (str(address),)

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443)
    except (OSError, socket.gaierror) as exc:
        raise ExternalGatewayPolicyError("external endpoint DNS resolution failed") from exc

    addresses: list[str] = []
    for _family, _kind, _proto, _canonname, sockaddr in infos:
        try:
            resolved = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_forbidden_ip(resolved):
            raise ExternalGatewayPolicyError("external endpoint resolves to a forbidden IP")
        normalized = str(resolved)
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise ExternalGatewayPolicyError("external endpoint resolves to no IP addresses")
    return tuple(addresses)


class _PinnedNetworkBackend(httpcore.NetworkBackend):
    """Dial only addresses captured by :func:`resolve_external_url`."""

    def __init__(self, expected_host: str, addresses: Iterable[str]) -> None:
        self._expected_host = expected_host.casefold()
        self._addresses = tuple(dict.fromkeys(addresses))
        if not self._addresses:
            raise ExternalGatewayPolicyError("external endpoint resolved to no addresses")
        self._backend = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        if host.casefold() != self._expected_host:
            raise httpcore.ConnectError("external transport host mismatch")
        last_error: Exception | None = None
        for address in self._addresses:
            try:
                return self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # pragma: no cover - live network only
                last_error = exc
        raise httpcore.ConnectError("all resolved external addresses failed") from last_error


class _CoreResponseStream(httpx.SyncByteStream):
    def __init__(self, stream: Iterable[bytes]) -> None:
        self._stream = stream

    def __iter__(self) -> Iterator[bytes]:
        yield from self._stream

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()


class _PinnedHTTPTransport(httpx.BaseTransport):
    """HTTPX transport preserving the validated DNS snapshot for one request."""

    def __init__(self, expected_host: str, addresses: Iterable[str]) -> None:
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=4,
            max_keepalive_connections=2,
            keepalive_expiry=5.0,
            http1=True,
            http2=False,
            network_backend=_PinnedNetworkBackend(expected_host, addresses),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.SyncByteStream)
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        response = self._pool.handle_request(core_request)
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_CoreResponseStream(response.stream),
            extensions=response.extensions,
            request=request,
        )

    def close(self) -> None:
        self._pool.close()


class OwnedExternalHTTPGateway:
    """POST only to code-owned non-data endpoint identifiers."""

    def __init__(
        self,
        endpoints: Mapping[str, ExternalEndpointSpec],
        *,
        transport: httpx.BaseTransport | None = None,
        max_request_bytes: int = 2_000_000,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        if max_request_bytes <= 0 or max_response_bytes <= 0:
            raise ValueError("external gateway byte budgets must be positive")
        self._endpoints = dict(endpoints)
        self._transport = transport
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._client = (
            httpx.Client(
                transport=transport,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0),
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
            if transport is not None
            else None
        )

    def post(
        self,
        endpoint_id: str,
        content: bytes,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_sec: int | float = 5.0,
    ) -> ExternalGatewayResponse:
        spec = self._endpoints.get(endpoint_id)
        if spec is None:
            raise ExternalGatewayPolicyError("unknown external endpoint identifier")
        if not isinstance(content, bytes):
            raise ExternalGatewayPolicyError("external request body must be bytes")
        if len(content) > self._max_request_bytes:
            raise ExternalGatewayPolicyError("external request exceeds byte budget")
        try:
            bounded_timeout = max(1.0, min(float(timeout_sec), 60.0))
        except (TypeError, ValueError) as exc:
            raise ExternalGatewayPolicyError("external timeout is invalid") from exc
        timeout = httpx.Timeout(
            connect=5.0,
            read=bounded_timeout,
            write=5.0,
            pool=5.0,
        )

        addresses: tuple[str, ...] = ()
        pinned_client: httpx.Client | None = None
        client = self._client
        if self._transport is None:
            addresses = resolve_external_url(spec.url)
            host = (urlparse(spec.url).hostname or "").casefold()
            pinned_client = httpx.Client(
                transport=_PinnedHTTPTransport(host, addresses),
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0),
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
            client = pinned_client
        assert client is not None
        try:
            with client.stream(
                "POST",
                spec.url,
                content=content,
                headers=dict(headers or {}),
                timeout=timeout,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise ExternalGatewayPolicyError("external redirects are disabled")
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self._max_response_bytes:
                    raise ExternalGatewayResponseTooLarge("external response exceeds byte budget")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_response_bytes:
                        raise ExternalGatewayResponseTooLarge("external response exceeds byte budget")
                return ExternalGatewayResponse(
                    status_code=response.status_code,
                    headers={key: value for key, value in response.headers.items()},
                    content=bytes(body),
                )
        except ExternalGatewayError:
            raise
        except (
            httpcore.NetworkError,
            httpcore.ProtocolError,
            httpcore.TimeoutException,
            httpx.HTTPError,
            ValueError,
        ) as exc:
            raise ExternalGatewayError("external sink transport failed") from exc
        finally:
            if pinned_client is not None:
                pinned_client.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> "OwnedExternalHTTPGateway":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


__all__ = [
    "ExternalEndpointSpec",
    "ExternalGatewayError",
    "ExternalGatewayPolicyError",
    "ExternalGatewayResponse",
    "ExternalGatewayResponseTooLarge",
    "OwnedExternalHTTPGateway",
    "redact_sink_text",
    "resolve_external_url",
]
