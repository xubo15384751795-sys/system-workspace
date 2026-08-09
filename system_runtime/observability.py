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
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_SENTRY_INITIALIZED = False


def _disabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return os.environ.get("OBSERVABILITY_DISABLE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    if _disabled():
        return
    if not init_sentry():
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001
        logger.debug("sentry capture_exception failed", exc_info=True)


def capture_message(message: str, *, level: str = "error", tags: dict[str, str] | None = None) -> None:
    if _disabled():
        return
    if not init_sentry():
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for key, value in (tags or {}).items():
                scope.set_tag(key, value)
            sentry_sdk.capture_message(message, level=level)
    except Exception:  # noqa: BLE001
        logger.debug("sentry capture_message failed", exc_info=True)


def _datadog_event(title: str, text: str, *, alert_type: str = "error", tags: list[str] | None = None) -> bool:
    api_key = os.environ.get("DD_API_KEY", "").strip()
    if not api_key:
        return False
    site = os.environ.get("DD_SITE", "datadoghq.com").strip() or "datadoghq.com"
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
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "DD-API-KEY": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("datadog event failed: %s", exc)
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

    level = "warning" if severity in {"warn", "warning"} else "error"
    tag_pairs = tags or {}
    capture_message(f"{title}: {message}", level=level, tags=tag_pairs)
    result["sentry"] = bool(os.environ.get("SENTRY_DSN", "").strip()) and init_sentry()

    dd_tags = [f"{k}:{v}" for k, v in tag_pairs.items()]
    alert_type = "warning" if level == "warning" else "error"
    result["datadog"] = _datadog_event(title, message, alert_type=alert_type, tags=dd_tags)
    return result
