from __future__ import annotations

import ipaddress
import os
import sys
from typing import Any

DEFAULT_API_KEY_ENV = "TERMINAL_API_KEY"
LOCAL_BIND_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_loopback_host(host: str) -> bool:
    """Return True when *host* only accepts local connections."""
    normalized = (host or "").strip().lower()
    if normalized in LOCAL_BIND_HOSTS:
        return True
    try:
        parsed = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return parsed.is_loopback


def resolve_api_key(config: dict[str, Any] | None = None) -> str:
    """Resolve API key from config and environment (config wins over env)."""
    api_cfg = (config or {}).get("api") or {}
    if isinstance(api_cfg.get("key"), str) and api_cfg["key"].strip():
        return api_cfg["key"].strip()
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
