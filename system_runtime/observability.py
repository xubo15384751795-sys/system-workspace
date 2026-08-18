"""Optional Sentry + Datadog sinks for operator alerts.

Configured entirely by environment variables; no-ops when unset so local and
CI runs stay silent without credentials.

Env:
  SENTRY_DSN              — enable Sentry exception/message capture
  SENTRY_ENVIRONMENT      — optional environment tag (default: system)
  DD_API_KEY              — Datadog API key for Events API v1
  DD_SITE                 — datadoghq.com (default) or datadoghq.eu / ...
  DD_SERVICE              — service tag (default: structural-risk-workbench)
  OBSERVABILITY_DISABLE   — if set truthy, skip all remote sinks
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from system_runtime.external_http import (
    ExternalEndpointSpec,
    ExternalGatewayError,
    OwnedExternalHTTPGateway,
    redact_sink_text,
)

logger = logging.getLogger(__name__)

_SENTRY_INITIALIZED = False
_DATADOG_SITES = frozenset(
    {
        "datadoghq.com",
        "datadoghq.eu",
        "us3.datadoghq.com",
        "us5.datadoghq.com",
        "ap1.datadoghq.com",
        "ddog-gov.com",
    }
)
_SENSITIVE_TAG_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "dsn",
        "password",
        "secret",
        "token",
    }
)
_ALLOWED_ATTRIBUTE_NAMES = frozenset(
    {
        "event_type",
        "generation",
        "generation_id",
        "release",
        "release_id",
        "run",
        "run_id",
        "service",
        "severity",
        "source",
        "status",
        "step",
    }
)


def _disabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    disabled_values = {"1", "true", "yes", "on"}
    return any(
        os.environ.get(name, "").strip().lower() in disabled_values
        for name in ("OBSERVABILITY_DISABLE", "NOTIFY_DISABLE")
    )


def _sanitize_tags(tags: dict[str, str] | None) -> dict[str, str]:
    """Keep only bounded, non-sensitive operational attributes."""
    safe: dict[str, str] = {}
    for raw_key, raw_value in (tags or {}).items():
        key = str(raw_key).casefold().replace("-", "_")
        if key not in _ALLOWED_ATTRIBUTE_NAMES or key in _SENSITIVE_TAG_NAMES:
            continue
        if not isinstance(raw_value, (str, int, float, bool)):
            continue
        value = redact_sink_text(raw_value).strip()
        if not value or len(value) > 128:
            continue
        if value.lstrip().startswith(("{", "[")):
            continue
        safe[key] = value
    return safe


def init_sentry() -> bool:
    """Initialize Sentry once when SENTRY_DSN is present."""
    global _SENTRY_INITIALIZED
    if _disabled() or _SENTRY_INITIALIZED:
        return _SENTRY_INITIALIZED
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "system"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0") or 0),
        send_default_pii=False,
    )
    _SENTRY_INITIALIZED = True
    return True


def capture_exception(exc: BaseException) -> None:
    """Capture a sanitized exception representation without raw credentials."""
    if _disabled():
        return
    if not init_sentry():
        return
    try:
        import sentry_sdk

        safe_exception = RuntimeError(
            f"{type(exc).__name__}: {redact_sink_text(exc)}"
        )
        sentry_sdk.capture_exception(safe_exception)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sentry capture_exception failed: %s", type(exc).__name__)


def capture_message(message: str, *, level: str = "error", tags: dict[str, str] | None = None) -> None:
    if _disabled():
        return
    if not init_sentry():
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in _sanitize_tags(tags).items():
                scope.set_tag(key, value)
            sentry_sdk.capture_message(redact_sink_text(message), level=level)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sentry capture_message failed: %s", type(exc).__name__)


def _datadog_event(title: str, text: str, *, alert_type: str = "error", tags: list[str] | None = None) -> bool:
    api_key = os.environ.get("DD_API_KEY", "").strip()
    if not api_key:
        return False
    site = os.environ.get("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"
    if site not in _DATADOG_SITES:
        logger.warning("datadog event skipped: invalid site configuration")
        return False
    service = os.environ.get("DD_SERVICE", "structural-risk-workbench")
    url = f"https://api.{site}/api/v1/events"
    payload = {
        "title": title[:100],
        "text": text[:4000],
        "alert_type": alert_type,
        "source_type_name": "python",
        "date_happened": int(datetime.now(UTC).timestamp()),
        "tags": [f"service:{service}", *(tags or [])],
    }
    try:
        host = urlparse(url).hostname or ""
        endpoint = ExternalEndpointSpec(
            endpoint_id="datadog_events",
            url=url,
            allowed_hosts=frozenset({host}),
        )
        with OwnedExternalHTTPGateway({"datadog_events": endpoint}) as gateway:
            response = gateway.post(
                "datadog_events",
                json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "DD-API-KEY": api_key,
                },
                timeout_sec=5,
            )
            return 200 <= response.status_code < 300
    except (ExternalGatewayError, ValueError) as exc:
        logger.warning("datadog event failed: %s", type(exc).__name__)
        return False


def emit_alert(
    title: str,
    message: str,
    *,
    severity: str = "error",
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fan-out alert to configured observability sinks.

    Returns which sinks accepted the event.
    """
    result = {"sentry": False, "datadog": False}
    if _disabled():
        return result

    safe_title = redact_sink_text(title)
    safe_message = redact_sink_text(message)
    safe_tags = _sanitize_tags(tags)
    level = "warning" if severity in {"warn", "warning"} else "error"
    capture_message(f"{safe_title}: {safe_message}", level=level, tags=safe_tags)
    result["sentry"] = bool(os.environ.get("SENTRY_DSN", "").strip()) and init_sentry()

    dd_tags = [f"{k}:{v}" for k, v in safe_tags.items()]
    alert_type = "warning" if level == "warning" else "error"
    result["datadog"] = _datadog_event(
        safe_title,
        safe_message,
        alert_type=alert_type,
        tags=dd_tags,
    )
    return result
