"""Owned outbound HTTP gateway for provider-owned endpoint identifiers.

The gateway deliberately does not accept a caller-supplied URL.  Providers
select a registered ``(provider, endpoint_id)`` pair and pass bounded query
parameters; transport policy is applied in one place.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from string import Formatter
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import quote, unquote, urlparse

import httpcore
import httpx

from src.api.security import (
    SSRFBlockedError,
    resolve_outbound_url,
    validate_outbound_url,
)


class GatewayError(RuntimeError):
    """Base error whose message never contains request parameters or URLs."""


class GatewayPolicyError(GatewayError):
    """Raised when an endpoint or transport policy rejects a request."""


class GatewayHTTPError(GatewayError):
    """Raised for non-success responses without exposing response content."""


class GatewayResponseTooLarge(GatewayPolicyError):
    """Raised when a response exceeds the configured byte budget."""


class _PinnedNetworkBackend(httpcore.NetworkBackend):
    """Connect only to addresses captured by the outbound URL validator."""

    def __init__(self, expected_host: str, addresses: Iterable[str]) -> None:
        self._expected_host = expected_host.casefold()
        self._addresses = tuple(dict.fromkeys(addresses))
        if not self._addresses:
            raise GatewayPolicyError("outbound endpoint resolved to no addresses")
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
            raise httpcore.ConnectError("outbound transport host mismatch")
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
            except Exception as exc:  # pragma: no cover - exercised by live network
                last_error = exc
        raise httpcore.ConnectError("all resolved outbound addresses failed") from last_error


class _CoreResponseStream(httpx.SyncByteStream):
    """Adapt an httpcore response stream to HTTPX's transport protocol."""

    def __init__(self, stream: Iterable[bytes]) -> None:
        self._stream = stream

    def __iter__(self) -> Iterator[bytes]:
        yield from self._stream

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()


class _PinnedHTTPTransport(httpx.BaseTransport):
    """HTTPX transport whose TCP dialer uses one validated DNS snapshot."""

    def __init__(
        self,
        expected_host: str,
        addresses: Iterable[str],
        *,
        max_connections: int = 10,
        max_keepalive_connections: int = 5,
    ) -> None:
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
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


@dataclass(frozen=True)
class EndpointSpec:
    provider: str
    endpoint_id: str
    url: str
    allowed_hosts: frozenset[str]
    path_parameters: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() != "https" or not host:
            raise GatewayPolicyError("registered endpoint must be an HTTPS URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise GatewayPolicyError("registered endpoint contains forbidden URL parts")
        fields = {
            name
            for _literal, name, _format_spec, _conversion in Formatter().parse(self.url)
            if name
        }
        if fields != set(self.path_parameters):
            raise GatewayPolicyError("registered endpoint path parameters are not explicit")
        if "{" in (parsed.netloc or "") or "}" in (parsed.netloc or ""):
            raise GatewayPolicyError("registered endpoint host cannot be templated")
        if host not in {item.lower() for item in self.allowed_hosts}:
            raise GatewayPolicyError("registered endpoint host is not allowlisted")


@dataclass(frozen=True)
class GatewayResponse:
    """Bounded response value detached from the live HTTPX client."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)

    def raise_for_status(self) -> None:
        if not 200 <= self.status_code < 300:
            raise GatewayHTTPError(f"provider response status={self.status_code}")


DEFAULT_ENDPOINTS: dict[tuple[str, str], EndpointSpec] = {
    ("fred", "series_observations"): EndpointSpec(
        provider="fred",
        endpoint_id="series_observations",
        url="https://api.stlouisfed.org/fred/series/observations",
        allowed_hosts=frozenset({"api.stlouisfed.org"}),
    ),
    ("h41", "ddp_csv"): EndpointSpec(
        provider="h41",
        endpoint_id="ddp_csv",
        url="https://www.federalreserve.gov/datadownload/Download.aspx",
        allowed_hosts=frozenset({"www.federalreserve.gov"}),
    ),
    ("sec", "submissions"): EndpointSpec(
        provider="sec",
        endpoint_id="submissions",
        url="https://data.sec.gov/submissions/CIK0000000000.json",
        allowed_hosts=frozenset({"data.sec.gov"}),
    ),
    ("treasury", "fiscal_service"): EndpointSpec(
        provider="treasury",
        endpoint_id="fiscal_service",
        url="https://api.fiscaldata.treasury.gov/services/api/fiscal_service",
        allowed_hosts=frozenset({"api.fiscaldata.treasury.gov"}),
    ),
    ("cboe", "daily_prices"): EndpointSpec(
        provider="cboe",
        endpoint_id="daily_prices",
        url="https://cdn.cboe.com/api/global/us_indices/daily_prices/INDEX_History.csv",
        allowed_hosts=frozenset({"cdn.cboe.com"}),
    ),
    ("historical_replay", "fred_graph"): EndpointSpec(
        provider="historical_replay",
        endpoint_id="fred_graph",
        url="https://fred.stlouisfed.org/graph/fredgraph.csv",
        allowed_hosts=frozenset({"fred.stlouisfed.org"}),
    ),
    ("research_brevan_howard", "bhmacro_document"): EndpointSpec(
        provider="research_brevan_howard",
        endpoint_id="bhmacro_document",
        url="https://www.bhmacro.com/{path}",
        allowed_hosts=frozenset({"www.bhmacro.com"}),
        path_parameters=frozenset({"path"}),
    ),
    ("research_brevan_howard", "brevanhoward_document"): EndpointSpec(
        provider="research_brevan_howard",
        endpoint_id="brevanhoward_document",
        url="https://www.brevanhoward.com/{path}",
        allowed_hosts=frozenset({"www.brevanhoward.com"}),
        path_parameters=frozenset({"path"}),
    ),
}


class OwnedHTTPGateway:
    """Single egress owner exposing only ``fetch(provider, endpoint_id, params)``."""

    def __init__(
        self,
        endpoint_registry: Mapping[tuple[str, str], EndpointSpec] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        headers: Mapping[str, str] | None = None,
        max_response_bytes: int = 2_000_000,
        timeout_sec: int | float = 30.0,
    ) -> None:
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if not 1.0 <= float(timeout_sec) <= 300.0:
            raise ValueError("timeout_sec must be between 1 and 300 seconds")
        self._endpoints = dict(endpoint_registry or DEFAULT_ENDPOINTS)
        self._max_response_bytes = max_response_bytes
        self._headers = dict(headers or {})
        self._timeout_sec = float(timeout_sec)
        self._transport = transport
        self._client = (
            httpx.Client(
                transport=transport,
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(connect=5.0, read=self._timeout_sec, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
            if transport is not None
            else None
        )

    def fetch(
        self,
        provider: str,
        endpoint_id: str,
        params: Mapping[str, object] | None = None,
    ) -> GatewayResponse:
        """Fetch a registered endpoint with bounded, non-redirecting transport."""
        key = (str(provider).strip().lower(), str(endpoint_id).strip())
        spec = self._endpoints.get(key)
        if spec is None:
            raise GatewayPolicyError("unknown provider or endpoint identifier")
        query, path_params = self._partition_params(spec, params or {})
        self._validate_params(query)
        url = self._render_url(spec, path_params)
        try:
            if self._transport is None:
                resolved_addresses = resolve_outbound_url(url)
            else:
                validate_outbound_url(url)
                resolved_addresses = ()
        except SSRFBlockedError as exc:
            raise GatewayPolicyError("registered endpoint failed outbound URL policy") from exc
        host = (urlparse(url).hostname or "").lower()
        if host not in {item.lower() for item in spec.allowed_hosts}:
            raise GatewayPolicyError("endpoint host is outside provider allowlist")

        pinned_client: httpx.Client | None = None
        client = self._client
        if self._transport is None:
            pinned_transport = _PinnedHTTPTransport(host, resolved_addresses)
            pinned_client = httpx.Client(
                transport=pinned_transport,
                headers=self._headers,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(connect=5.0, read=self._timeout_sec, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
            client = pinned_client

        assert client is not None
        try:
            with client.stream(
                "GET",
                url,
                params=dict(query),
            ) as response:
                if 300 <= response.status_code < 400:
                    raise GatewayPolicyError("redirects are disabled for provider egress")
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self._max_response_bytes:
                    raise GatewayResponseTooLarge("provider response exceeds byte budget")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_response_bytes:
                        raise GatewayResponseTooLarge("provider response exceeds byte budget")
                return GatewayResponse(
                    status_code=response.status_code,
                    headers={key: value for key, value in response.headers.items()},
                    content=bytes(body),
                )
        except GatewayError:
            raise
        except (
            httpcore.NetworkError,
            httpcore.ProtocolError,
            httpcore.TimeoutException,
            httpx.HTTPError,
            ValueError,
        ) as exc:
            raise GatewayError(f"provider transport failed: {key[0]}/{key[1]}") from exc
        finally:
            if pinned_client is not None:
                pinned_client.close()

    @staticmethod
    def _partition_params(
        spec: EndpointSpec,
        params: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, str]]:
        """Split one bounded parameter map into registered path/query values."""
        query: dict[str, object] = {}
        path: dict[str, str] = {}
        for name, value in params.items():
            if not isinstance(name, str):
                raise GatewayPolicyError("provider query parameter name is invalid")
            if name in spec.path_parameters:
                if not isinstance(value, str):
                    raise GatewayPolicyError("provider path parameter is invalid")
                path[name] = value
            else:
                query[name] = value
        return query, path

    @staticmethod
    def _validate_params(params: Mapping[str, object]) -> None:
        for name, value in params.items():
            if not isinstance(name, str) or not name or len(name) > 128:
                raise GatewayPolicyError("provider query parameter name is invalid")
            values = value if isinstance(value, (list, tuple)) else (value,)
            if len(values) > 64:
                raise GatewayPolicyError("provider query parameter has too many values")
            for item in values:
                if item is None:
                    continue
                if not isinstance(item, (str, int, float, bool)):
                    raise GatewayPolicyError("provider query parameter value is invalid")
                if isinstance(item, str) and len(item) > 1024:
                    raise GatewayPolicyError("provider query parameter value is too long")

    @staticmethod
    def _render_url(spec: EndpointSpec, path_params: Mapping[str, str]) -> str:
        fields = {
            name
            for _literal, name, _format_spec, _conversion in Formatter().parse(spec.url)
            if name
        }
        if fields != set(path_params):
            raise GatewayPolicyError("provider path parameters do not match endpoint contract")

        rendered: dict[str, str] = {}
        for name, value in path_params.items():
            if not isinstance(value, str) or len(value) > 2048:
                raise GatewayPolicyError("provider path parameter is invalid")
            if name == "path":
                decoded = unquote(value).lstrip("/")
                if not decoded:
                    rendered[name] = ""
                    continue
                if any(char in decoded for char in "?#\\\r\n"):
                    raise GatewayPolicyError("provider path parameter contains unsafe characters")
                if any(segment in {".", ".."} for segment in decoded.split("/")):
                    raise GatewayPolicyError("provider path parameter contains unsafe segments")
                rendered[name] = quote(decoded, safe="/._-~")
            else:
                if not value or not all(char.isalnum() or char in "._-" for char in value):
                    raise GatewayPolicyError("provider path parameter contains unsafe characters")
                rendered[name] = quote(value, safe="._-~")
        try:
            return spec.url.format(**rendered)
        except (KeyError, ValueError) as exc:
            raise GatewayPolicyError("provider path parameter rendering failed") from exc

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> "OwnedHTTPGateway":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


__all__ = [
    "DEFAULT_ENDPOINTS",
    "EndpointSpec",
    "GatewayError",
    "GatewayHTTPError",
    "GatewayPolicyError",
    "GatewayResponse",
    "GatewayResponseTooLarge",
    "OwnedHTTPGateway",
]
