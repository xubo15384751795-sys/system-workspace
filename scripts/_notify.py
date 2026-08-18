"""Exception-only desktop and remote notifications.

Channels (in priority order):
  1. macOS desktop notification (osascript) — always attempted on Darwin
  2. Webhook (HTTP POST) — if NOTIFY_WEBHOOK_URL env var is set

Webhook payload:
  {"title": "...", "message": "...", "status": "...", "timestamp": "..."}

Configure:
  export NOTIFY_WEBHOOK_URL="https://hooks.slack.com/services/..."   # Slack
  export NOTIFY_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..."  # Feishu
  export NOTIFY_WEBHOOK_URL="https://your-server.com/webhook"        # Generic

Observability (optional; see system_runtime.observability):
  export SENTRY_DSN="https://...@sentry.io/..."
  export DD_API_KEY="..."
  export DD_SITE="datadoghq.com"   # or datadoghq.eu
"""
from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from scripts._constants import TIMEOUT_SHORT
from system_runtime.external_http import (
    ExternalEndpointSpec,
    ExternalGatewayError,
    OwnedExternalHTTPGateway,
    redact_sink_text,
)

logger = logging.getLogger(__name__)


def _notification_state_path() -> Path:
    output_root = os.environ.get("DAILY_OUTPUT_ROOT", "").strip()
    root = Path(output_root) if output_root else Path(__file__).resolve().parents[1] / "Output"
    return root / "alerts" / ".notification_state.json"


def _dedup_notification(
    *,
    status: str,
    failed_steps: list[str],
    warnings: list[str],
    outcome: dict[str, object] | None,
) -> bool:
    """Return True when the same root cause was already notified recently."""
    if _suppression_reason():
        return False
    from system_runtime.minimum_monitoring import notification_dedup_key

    provider_status = str((outcome or {}).get("provider_status") or "").strip() or None
    # Dynamic freshness ages should not create a new notification for the same
    # provider outage.  The typed provider/root status is the stable signal.
    stable_warnings = [] if provider_status else warnings
    key = notification_dedup_key(
        run_id=str((outcome or {}).get("run_id") or ""),
        status=status,
        failed_steps=failed_steps,
        warnings=stable_warnings,
        outcome=outcome,
        provider_status=provider_status,
    )
    path = _notification_state_path()
    now = time.time()
    try:
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        previous = {}
    try:
        window = max(0.0, float(os.environ.get("NOTIFY_DEDUP_WINDOW_S", str(24 * 3600))))
    except ValueError:
        window = float(24 * 3600)
    if (
        isinstance(previous, dict)
        and previous.get("key") == key
        and now - float(previous.get("notified_at", 0) or 0) < window
    ):
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"key": key, "notified_at": now}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        logger.warning("Unable to persist notification dedup state", exc_info=True)
    return False


def _notify_webhook(title: str, message: str) -> bool:
    """Send notification via webhook if NOTIFY_WEBHOOK_URL is configured."""
    webhook_url = os.environ.get("NOTIFY_WEBHOOK_URL", "")
    if not webhook_url:
        return False

    payload = json.dumps({
        "title": title,
        "message": message,
        "timestamp": datetime.now(UTC).isoformat(),
    }).encode("utf-8")

    # Slack-compatible payload (also works for Feishu, generic webhooks)
    if "hooks.slack.com" in webhook_url or "open.feishu.cn" in webhook_url:
        payload = json.dumps({
            "text": f"*{title}*\n{message}",
        }).encode("utf-8")

    try:
        host = urlparse(webhook_url).hostname or ""
        endpoint = ExternalEndpointSpec(
            endpoint_id="notification_webhook",
            url=webhook_url,
            allowed_hosts=frozenset({host}),
        )
        with OwnedExternalHTTPGateway({"notification_webhook": endpoint}) as gateway:
            response = gateway.post(
                "notification_webhook",
                payload,
                headers={"Content-Type": "application/json"},
                timeout_sec=TIMEOUT_SHORT,
            )
            return response.status_code < 400
    except (ExternalGatewayError, ValueError) as exc:
        # The exception may contain the configured URL or query parameters;
        # log only its type so notification failures cannot leak credentials.
        logger.warning("notification webhook delivery failed: %s", type(exc).__name__)
        return False


def _suppression_reason() -> str | None:
    """Why a real notification must not leave this process, or None to send.

    The pipeline steps are exercised against sandbox fixtures in the test
    suite. Those tests isolate their *outputs* correctly, but without this
    guard the notification itself escapes the sandbox into the operator's
    real notification centre carrying fixture dates (etf_panel behind=1118d),
    which buries genuine alerts among alarming-looking fakes.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "pytest"
    if os.environ.get("NOTIFY_DISABLE", "").strip().lower() not in ("", "0", "false"):
        return "NOTIFY_DISABLE"
    return None


def _notify_observability(title: str, message: str, *, severity: str = "error") -> None:
    """Fan-out to Sentry/Datadog when configured (independent of desktop/webhook)."""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("NOTIFY_DISABLE", "").strip().lower() not in ("", "0", "false"):
        return
    try:
        from system_runtime.observability import emit_alert

        emit_alert(
            title,
            message,
            severity=severity,
            tags={"source": "scripts._notify"},
        )
    except Exception as exc:  # noqa: BLE001 - sink failure must not break the daily path
        # Observability must never break the daily path, but a failed sink is
        # an explicit local degradation rather than an invisible success.
        logger.warning("observability notification failed: %s", type(exc).__name__)


def notify_failure(title: str, message: str, *, severity: str = "error") -> bool:
    """Show notification via all available channels. Returns True if any ran."""
    safe_title = redact_sink_text(title)
    safe_message = redact_sink_text(message)
    _notify_observability(safe_title, safe_message, severity=severity)
    suppressed = _suppression_reason()
    if suppressed:
        # Still visible to whoever is running, just not as a desktop alert.
        print(f"NOTIFY[suppressed:{suppressed}]: {safe_title} — {safe_message}", file=sys.stderr)
        return False
    desktop_ok = _notify_desktop(safe_title, safe_message)
    webhook_ok = _notify_webhook(safe_title, safe_message)
    return desktop_ok or webhook_ok


def notify_alert(title: str, message: str) -> bool:
    """Risk / stance alert (same channels as notify_failure; neutral naming)."""
    return notify_failure(title, message)


def notify_deviations(title: str, deviations: list[str], *, severity: str = "error") -> bool:
    """Notify only when deviations exist; normal state has zero output."""
    compact = [str(item).strip() for item in deviations if str(item).strip()]
    if not compact:
        return False
    preview = "; ".join(compact[:3])
    if len(compact) > 3:
        preview += f"; +{len(compact) - 3} more"
    return notify_failure(title, preview, severity=severity)


def _notify_desktop(title: str, message: str) -> bool:
    """Show a macOS desktop notification. Returns True if a notifier ran."""
    if platform.system() != "Darwin":
        print(f"NOTIFY: {title} — {message}", file=sys.stderr)
        return False

    safe_title = title.replace('"', "'")[:120]
    safe_message = message.replace('"', "'")[:240]
    script = (
        f'display notification "{safe_message}" '
        f'with title "{safe_title}" sound name "Basso"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=TIMEOUT_SHORT,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def notify_daily_run_result(
    *,
    status: str,
    failed_steps: list[str],
    warnings: list[str],
    outcome: dict[str, object] | None = None,
    canonical_lineage: dict[str, object] | None = None,
) -> None:
    outcome_suffix = ""
    if outcome:
        outcome_suffix = (
            f"; exit_code={outcome.get('exit_code')}"
            f"; admission={outcome.get('admission_verdict')}"
            f"; publish={outcome.get('publish_status')}"
        )
        if outcome.get("provider_status"):
            outcome_suffix += f"; provider={outcome.get('provider_status')}"
    if canonical_lineage:
        lineage_status = str(canonical_lineage.get("status") or "UNAVAILABLE")
        # Canonical lineage is a shadow reader context.  Surface its state in
        # an existing failure/warning notification without changing dedup or
        # granting any publication authority.
        outcome_suffix += f"; canonical_lineage={lineage_status}"
    outcome_failed = bool(outcome and int(outcome.get("exit_code") or 0) != 0)
    if status == "success" and not warnings and not outcome_failed:
        return
    outcome_degraded = bool(
        outcome
        and (
            outcome.get("status") == "degraded"
            or outcome.get("operational_state") == "COMPLETED_DEGRADED"
        )
    )
    if failed_steps or outcome_failed:
        if outcome_degraded and not failed_steps:
            title = "System daily_run warnings"
            severity = "warning"
        else:
            title = "System daily_run failed"
            severity = "error"
        if _dedup_notification(
            status=status,
            failed_steps=failed_steps,
            warnings=warnings,
            outcome=outcome,
        ):
            logger.info("Suppressed duplicate daily-run notification")
            return
        notify_deviations(
            title,
            [f"failed step: {step}" for step in failed_steps]
            + ([f"outcome{outcome_suffix}"] if outcome_suffix else ["outcome=missing"]),
            severity=severity,
        )
        return
    if warnings:
        if _dedup_notification(
            status=status,
            failed_steps=failed_steps,
            warnings=warnings,
            outcome=outcome,
        ):
            logger.info("Suppressed duplicate daily-run warning")
            return
        notify_deviations(
            "System daily_run warnings",
            [*warnings, f"outcome{outcome_suffix}", "details: Output/alerts/latest_alert.md"],
            severity="warning",
        )
