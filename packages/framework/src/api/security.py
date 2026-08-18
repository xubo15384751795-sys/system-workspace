from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse

DEFAULT_API_KEY_ENV = "TERMINAL_API_KEY"
LOCAL_BIND_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class SSRFBlockedError(Exception):
    """Raised when an outbound URL targets a forbidden host/scheme."""


def resolve_outbound_url(url: str) -> tuple[str, ...]:
    """Validate *url* and return the public addresses resolved for it.

    Rejects non-HTTPS schemes (including ``file://``), loopback / private /
    link-local / multicast / reserved IP addresses (after DNS resolution),
    userinfo, fragments, and empty hosts.  The returned addresses are the
    exact DNS results that an outbound transport must use for this request;
    resolving them again later would re-open a DNS-rebinding window.
    """
    if not url or not isinstance(url, str):
        raise SSRFBlockedError("empty URL")

    parsed = urlparse(url)

    if parsed.scheme.lower() != "https":
        raise SSRFBlockedError(f"non-https scheme: {parsed.scheme!r}")

    if "@" in (parsed.netloc or ""):
        raise SSRFBlockedError("userinfo not allowed in URL")

    if parsed.fragment:
        raise SSRFBlockedError("fragment not allowed in URL")

    host = parsed.hostname
    if not host:
        raise SSRFBlockedError("missing host")

    # Reject obvious textual loopback/private before DNS.
    host_lower = host.strip().lower()
    if host_lower in LOCAL_BIND_HOSTS:
        raise SSRFBlockedError(f"loopback host: {host}")
    # Bracket-less IPv6 literal e.g. [::1] is parsed by .hostname as ::1
    try:
        addr = ipaddress.ip_address(host_lower)
    except ValueError:
        addr = None
    if addr is not None and _is_forbidden_ip(addr):
        raise SSRFBlockedError(f"forbidden IP literal: {host}")
    if addr is not None:
        return (str(addr),)

    # DNS-resolve and check every returned address (catches DNS rebinding).
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"DNS resolution failed for {host}: {exc}") from exc

    addresses: list[str] = []
    for family, _stype, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip_addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_forbidden_ip(ip_addr):
            raise SSRFBlockedError(f"host {host} resolves to forbidden IP: {ip_str}")
        normalized = str(ip_addr)
        if normalized not in addresses:
            addresses.append(normalized)

    if not addresses:
        raise SSRFBlockedError(f"DNS resolution returned no IP addresses for {host}")
    return tuple(addresses)


def validate_outbound_url(url: str) -> str:
    """Validate that *url* is safe for outbound HTTP egress."""
    resolve_outbound_url(url)

    return url


def _is_forbidden_ip(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return True for loopback, private, link-local, multicast, or reserved IPs."""
    return bool(
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def is_loopback_host(host: str) -> bool:
    """Return True when *host* only accepts local connections."""
    normalized = (host or "").strip().lower()
    if normalized in LOCAL_BIND_HOSTS:
        return True
    try:
        parsed = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(parsed.is_loopback)


def resolve_api_key(config: dict[str, Any] | None = None) -> str:
    """Resolve API key from config and environment (config wins over env)."""
    api_cfg = (config or {}).get("api") or {}
    configured_key = api_cfg.get("key")
    if isinstance(configured_key, str) and configured_key.strip():
        return configured_key.strip()
    env_name = str(api_cfg.get("key_env") or DEFAULT_API_KEY_ENV).strip() or DEFAULT_API_KEY_ENV
    return os.environ.get(env_name, "").strip()


def assert_bind_allowed(host: str, *, api_key: str) -> None:
    """Refuse non-loopback binds unless an API key is configured."""
    if is_loopback_host(host):
        return
    if api_key:
        return
    raise SystemExit(
        "Refusing to bind the terminal API to a non-loopback host without an API key. "
        f"Set {DEFAULT_API_KEY_ENV} or pass api.key in config before using --host {host}."
    )


def install_api_key_middleware(app: Any, *, api_key: str) -> None:
    """Require X-API-Key (or Bearer token) on all routes except /health."""
    if not api_key:
        return

    try:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Install fastapi/starlette to enable API key middleware.") from exc

    class _APIKeyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path == "/health":
                return await call_next(request)
            presented = request.headers.get("x-api-key", "").strip()
            if not presented:
                auth = request.headers.get("authorization", "").strip()
                if auth.lower().startswith("bearer "):
                    presented = auth[7:].strip()
            if presented != api_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key"},
                )
            return await call_next(request)

    app.add_middleware(_APIKeyMiddleware)


def resolve_harvester_validation(config: dict[str, Any]) -> tuple[bool, bool]:
    """Read harvester integrity settings with secure defaults."""
    hcfg = config.get("harvester") or {}
    validate_hashes = hcfg.get("validate_hashes", True)
    validate_schema = hcfg.get("validate_schema", True)
    return bool(validate_hashes), bool(validate_schema)
