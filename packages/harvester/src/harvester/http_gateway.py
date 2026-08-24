"""Owned outbound HTTP gateway for Harvester provider endpoints.

Provider code selects a registered endpoint and bounded parameters.  It never
accepts a caller-supplied URL and never owns a raw ``requests`` session.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
from dataclasses import dataclass
from string import Formatter
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import urlparse

import httpcore
import httpx


class GatewayError(RuntimeError):
    """Base error whose message does not contain URLs or query parameters."""


class GatewayPolicyError(GatewayError):
    """Raised when an endpoint or transport policy rejects a request."""


class GatewayHTTPError(GatewayError):
    """Raised for non-success responses after the provider inspects the status."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"provider response status={status_code}")


class GatewayResponseTooLarge(GatewayPolicyError):
    """Raised when a provider response exceeds the configured byte budget."""


@dataclass(frozen=True)
class EndpointSpec:
    provider: str
    endpoint_id: str
    url: str
    allowed_hosts: frozenset[str]
    path_parameters: frozenset[str] = frozenset()
    proxy_env_var: str = ""

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
        if self.proxy_env_var and not self.proxy_env_var.isidentifier():
            raise GatewayPolicyError("registered endpoint proxy environment name is invalid")
        if "{" in (parsed.netloc or "") or "}" in (parsed.netloc or ""):
            raise GatewayPolicyError("registered endpoint host cannot be templated")
        if host not in {item.lower() for item in self.allowed_hosts}:
            raise GatewayPolicyError("registered endpoint host is not allowlisted")


@dataclass(frozen=True)
class GatewayResponse:
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
            raise GatewayHTTPError(self.status_code)


DEFAULT_ENDPOINTS: dict[tuple[str, str], EndpointSpec] = {
    ("fred", "series_observations"): EndpointSpec(
        provider="fred",
        endpoint_id="series_observations",
        url="https://api.stlouisfed.org/fred/series/observations",
        allowed_hosts=frozenset({"api.stlouisfed.org"}),
    ),
    ("fred", "series_graph"): EndpointSpec(
        provider="fred",
        endpoint_id="series_graph",
        url="https://fred.stlouisfed.org/graph/fredgraph.csv",
        allowed_hosts=frozenset({"fred.stlouisfed.org"}),
    ),
    ("h41", "ddp_csv"): EndpointSpec(
        provider="h41",
        endpoint_id="ddp_csv",
        url="https://www.federalreserve.gov/datadownload/DownloadTable.aspx",
        allowed_hosts=frozenset({"www.federalreserve.gov"}),
    ),
    ("treasury", "debt_to_penny"): EndpointSpec(
        provider="treasury",
        endpoint_id="debt_to_penny",
        url="https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny",
        allowed_hosts=frozenset({"api.fiscaldata.treasury.gov"}),
    ),
    ("treasury", "daily_treasury_statement"): EndpointSpec(
        provider="treasury",
        endpoint_id="daily_treasury_statement",
        url="https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance",
        allowed_hosts=frozenset({"api.fiscaldata.treasury.gov"}),
    ),
    ("sec", "submissions"): EndpointSpec(
        provider="sec",
        endpoint_id="submissions",
        url="https://data.sec.gov/submissions/CIK{cik}.json",
        allowed_hosts=frozenset({"data.sec.gov"}),
        path_parameters=frozenset({"cik"}),
    ),
    ("sec", "companyconcept"): EndpointSpec(
        provider="sec",
        endpoint_id="companyconcept",
        url="https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json",
        allowed_hosts=frozenset({"data.sec.gov"}),
        path_parameters=frozenset({"cik", "tag"}),
    ),
    ("cboe", "daily_prices"): EndpointSpec(
        provider="cboe",
        endpoint_id="daily_prices",
        url="https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv",
        allowed_hosts=frozenset({"cdn.cboe.com"}),
        path_parameters=frozenset({"symbol"}),
    ),
    ("cboe", "intraday_quotes"): EndpointSpec(
        provider="cboe",
        endpoint_id="intraday_quotes",
        url="https://cdn.cboe.com/api/global/delayed_quotes/quotes/_{symbol}.json",
        allowed_hosts=frozenset({"cdn.cboe.com"}),
        path_parameters=frozenset({"symbol"}),
    ),
    ("tiingo", "daily_prices"): EndpointSpec(
        provider="tiingo",
        endpoint_id="daily_prices",
        url="https://api.tiingo.com/tiingo/daily/{ticker}/prices",
        allowed_hosts=frozenset({"api.tiingo.com"}),
        path_parameters=frozenset({"ticker"}),
    ),
    ("massive", "daily_aggs"): EndpointSpec(
        provider="massive",
        endpoint_id="daily_aggs",
        url="https://api.massive.com/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}",
        allowed_hosts=frozenset({"api.massive.com"}),
        path_parameters=frozenset({"ticker", "multiplier", "timespan", "from_date", "to_date"}),
    ),
}


def _is_forbidden_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def resolve_outbound_url(url: str) -> tuple[str, ...]:
    """Validate *url* and return its one-request public DNS snapshot."""
    if not isinstance(url, str) or not url:
        raise GatewayPolicyError("empty outbound URL")
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise GatewayPolicyError("outbound URL must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise GatewayPolicyError("outbound URL contains forbidden URL parts")
    host = parsed.hostname
    if not host:
        raise GatewayPolicyError("outbound URL has no host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and _is_forbidden_ip(address):
        raise GatewayPolicyError("outbound URL targets a forbidden IP")
    if address is not None:
        return (str(address),)
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise GatewayPolicyError("outbound endpoint DNS resolution failed") from exc
    addresses: list[str] = []
    for _family, _kind, _proto, _canonname, sockaddr in infos:
        try:
            resolved = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_forbidden_ip(resolved):
            raise GatewayPolicyError("outbound endpoint resolves to a forbidden IP")
        normalized = str(resolved)
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise GatewayPolicyError("outbound endpoint resolves to no IP addresses")
    return tuple(addresses)


def validate_outbound_url(url: str) -> str:
    """Reject non-HTTPS, userinfo, fragments, and private DNS targets."""
    resolve_outbound_url(url)
    return url


def _configured_proxy_url(spec: EndpointSpec) -> str | None:
    """Return an explicitly opted-in, credential-free HTTP proxy URL.

    The gateway remains ``trust_env=False`` by default.  A registered endpoint
    may name one environment variable for a narrow exception; other registered
    endpoints use the explicit global ``HARVESTER_HTTP_PROXY_URL`` opt-in.
    The caller must set the selected variable deliberately.
    """
    proxy_env_var = spec.proxy_env_var or "HARVESTER_HTTP_PROXY_URL"
    proxy_url = os.environ.get(proxy_env_var, "").strip()
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or parsed.path not in {"", "/"}
    ):
        raise GatewayPolicyError("configured provider proxy is invalid")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise GatewayPolicyError("configured provider proxy is invalid") from exc
    return proxy_url


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


class OwnedHTTPGateway:
    """Single Harvester egress owner exposing provider endpoint identifiers."""

    def __init__(
        self,
        endpoint_registry: Mapping[tuple[str, str], EndpointSpec] | None = None,
        *,
        headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
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
                headers=self._headers,
                transport=transport,
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
        key = (str(provider).strip().lower(), str(endpoint_id).strip())
        spec = self._endpoints.get(key)
        if spec is None:
            raise GatewayPolicyError("unknown provider or endpoint identifier")
        query, path_params = self._partition_params(spec, params or {})
        self._validate_params(query)
        url = self._render_url(spec, path_params)
        proxy_url: str | None = None
        if self._transport is None:
            proxy_url = _configured_proxy_url(spec)
            if proxy_url:
                # Keep the registered endpoint allowlist and HTTPS validation;
                # only the TCP route changes to the explicitly configured
                # proxy.  Do not let HTTPX read arbitrary environment values.
                validate_outbound_url(url)
                resolved_addresses: tuple[str, ...] = ()
            else:
                resolved_addresses = resolve_outbound_url(url)
        else:
            validate_outbound_url(url)
            resolved_addresses = ()
        pinned_client: httpx.Client | None = None
        client = self._client
        try:
            if self._transport is None:
                if proxy_url:
                    pinned_client = httpx.Client(
                        headers=self._headers,
                        proxy=proxy_url,
                        follow_redirects=False,
                        trust_env=False,
                        timeout=httpx.Timeout(connect=5.0, read=self._timeout_sec, write=10.0, pool=5.0),
                        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                    )
                else:
                    pinned_transport = _PinnedHTTPTransport(
                        expected_host=(urlparse(url).hostname or ""),
                        addresses=resolved_addresses,
                    )
                    pinned_client = httpx.Client(
                        headers=self._headers,
                        transport=pinned_transport,
                        follow_redirects=False,
                        trust_env=False,
                        timeout=httpx.Timeout(connect=5.0, read=self._timeout_sec, write=10.0, pool=5.0),
                        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                    )
                client = pinned_client
            assert client is not None
            # Passing an empty mapping makes HTTPX rebuild the URL without a
            # query on some versions.  ``EndpointSpec.url`` may itself carry
            # a registered, bounded query (ECB/CFTC); preserve it explicitly.
            request_params = query if query else None
            with client.stream("GET", url, params=request_params) as response:
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
                    headers=dict(response.headers),
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
        for name, value in path_params.items():
            if not isinstance(value, str) or not value or len(value) > 128:
                raise GatewayPolicyError("provider path parameter is invalid")
            if not all(char.isalnum() or char in "._-" for char in value):
                raise GatewayPolicyError("provider path parameter contains unsafe characters")
        try:
            return spec.url.format(**path_params)
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
    "resolve_outbound_url",
    "validate_outbound_url",
]
