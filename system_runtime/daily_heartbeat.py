"""Local daily-run heartbeat and optional healthchecks.io ping.

The local heartbeat is the durable ``I ran`` signal.  A healthchecks.io ping
is an optional second sink; it is never allowed to replace the local record or
change the typed daily-run outcome.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from system_runtime.external_http import (
    ExternalEndpointSpec,
    ExternalGatewayError,
    OwnedExternalHTTPGateway,
)

logger = logging.getLogger(__name__)

HEARTBEAT_FILENAME = "daily_run_heartbeat.json"
HEALTHCHECKS_HOSTS = frozenset(
    {"healthchecks.io", "www.healthchecks.io", "hc-ping.com", "www.hc-ping.com"}
)


def default_output_root() -> Path:
    configured = os.environ.get("DAILY_OUTPUT_ROOT", "").strip()
    if configured:
        return Path(configured)
    system_root = os.environ.get("SYSTEM_ROOT", "").strip() or os.environ.get(
        "SYSTEM_WORKSPACE_ROOT", ""
    ).strip()
    if system_root:
        return Path(system_root) / "Output"
    return Path(__file__).resolve().parents[1] / "Output"


def heartbeat_path(output_root: Path | None = None) -> Path:
    configured = os.environ.get("DAILY_RUN_HEARTBEAT_PATH", "").strip()
    if configured:
        return Path(configured)
    return (output_root or default_output_root()) / "health" / HEARTBEAT_FILENAME


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _remote_sinks_disabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    disabled = {"1", "true", "yes", "on"}
    return any(
        os.environ.get(name, "").strip().lower() in disabled
        for name in ("OBSERVABILITY_DISABLE", "NOTIFY_DISABLE")
    )


def _ping_healthchecks(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in HEALTHCHECKS_HOSTS or parsed.query or parsed.fragment:
        logger.warning("healthchecks ping skipped: invalid endpoint configuration")
        return False
    endpoint = ExternalEndpointSpec(
        endpoint_id="healthchecks_ping",
        url=url,
        allowed_hosts=frozenset({host}),
    )
    try:
        with OwnedExternalHTTPGateway({"healthchecks_ping": endpoint}) as gateway:
            response = gateway.post(
                "healthchecks_ping",
                b"",
                headers={"Content-Type": "text/plain"},
                timeout_sec=5,
            )
        return 200 <= response.status_code < 300
    except (ExternalGatewayError, ValueError) as exc:
        logger.warning("healthchecks ping failed: %s", type(exc).__name__)
        return False


def write_daily_run_heartbeat(
    outcome: Mapping[str, Any],
    *,
    output_root: Path | None = None,
    source: str | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Atomically write the latest typed daily-run outcome as a heartbeat."""
    timestamp = observed_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
    payload: dict[str, Any] = {
        "schema_version": "system.daily_run_heartbeat.v1",
        "observed_at": timestamp.isoformat(),
        "run_id": str(outcome.get("run_id") or ""),
        "status": str(outcome.get("status") or "unknown"),
        "exit_code": int(outcome.get("exit_code") or 0),
        "operational_state": str(outcome.get("operational_state") or ""),
        "source": source or os.environ.get("SYSTEM_RUN_ORIGIN", "manual"),
        "healthchecks": "not_configured",
    }
    path = heartbeat_path(output_root)
    _atomic_write_json(path, payload)

    healthchecks_url = os.environ.get("HEALTHCHECKS_DAILY_RUN_URL", "").strip()
    if healthchecks_url and not _remote_sinks_disabled():
        payload["healthchecks"] = "sent" if _ping_healthchecks(healthchecks_url) else "failed"
        _atomic_write_json(path, payload)
    return payload


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def check_daily_run_heartbeat(
    *,
    output_root: Path | None = None,
    now: datetime | None = None,
    max_age_hours: float | None = None,
) -> dict[str, Any]:
    """Return a PASS/ALERT report for the independent dead-man checker."""
    path = heartbeat_path(output_root)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    try:
        configured_age = float(
            os.environ.get("DAILY_RUN_HEARTBEAT_MAX_AGE_HOURS", "26")
            if max_age_hours is None
            else max_age_hours
        )
    except (TypeError, ValueError):
        configured_age = 26.0
    configured_age = max(1.0, configured_age)

    report: dict[str, Any] = {
        "schema_version": "system.daily_run_deadman.v1",
        "checked_at": current.isoformat(),
        "heartbeat_path": str(path),
        "max_age_hours": configured_age,
    }
    if not path.is_file():
        report.update({"status": "ALERT", "reason": "heartbeat_missing"})
        return report
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report.update({"status": "ALERT", "reason": "heartbeat_unreadable"})
        return report
    if not isinstance(payload, dict):
        report.update({"status": "ALERT", "reason": "heartbeat_invalid"})
        return report
    observed = _parse_timestamp(payload.get("observed_at"))
    if observed is None:
        report.update({"status": "ALERT", "reason": "heartbeat_timestamp_invalid"})
        return report
    age_hours = max(0.0, (current - observed).total_seconds() / 3600.0)
    report.update(
        {
            "status": "PASS" if age_hours <= configured_age else "ALERT",
            "reason": "heartbeat_fresh" if age_hours <= configured_age else "heartbeat_stale",
            "age_hours": round(age_hours, 3),
            "last_run_id": payload.get("run_id"),
            "last_status": payload.get("status"),
            "last_exit_code": payload.get("exit_code"),
        }
    )
    return report


__all__ = [
    "HEARTBEAT_FILENAME",
    "check_daily_run_heartbeat",
    "default_output_root",
    "heartbeat_path",
    "write_daily_run_heartbeat",
]
