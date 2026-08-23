"""Exception-only desktop and remote notifications.

Channels (in priority order):
  1. macOS desktop notification (osascript) — always attempted on Darwin
  2. Webhook (HTTP POST) — if NOTIFY_WEBHOOK_URL env var is set
  3. Telegram Bot private chat — if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set
  4. Legacy Feishu bot webhook — if FEISHU_WEBHOOK_URL env var is set and Telegram is absent

Webhook payload:
  {"title": "...", "message": "...", "status": "...", "timestamp": "..."}

Configure:
  export NOTIFY_WEBHOOK_URL="https://hooks.slack.com/services/..."   # Slack
  export NOTIFY_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..."  # Feishu
  export NOTIFY_WEBHOOK_URL="https://your-server.com/webhook"        # Generic
  export TELEGRAM_BOT_TOKEN="123456789:..."
  export TELEGRAM_CHAT_ID="123456789"
  export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/..."

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
from datetime import UTC, date, datetime
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
_FEISHU_HOSTS = frozenset({"open.feishu.cn", "open.larksuite.com"})
_TELEGRAM_HOST = "api.telegram.org"
_TELEGRAM_MAX_TEXT = 4096


def _notification_state_path() -> Path:
    output_root = os.environ.get("DAILY_OUTPUT_ROOT", "").strip()
    root = Path(output_root) if output_root else Path(__file__).resolve().parents[1] / "Output"
    return root / "alerts" / ".notification_state.json"


def _dedup_now() -> datetime:
    """Clock seam for the calendar-day notification recurrence protocol."""
    return datetime.now(UTC)


def _repeat_escalation_days() -> int:
    try:
        configured = int(os.environ.get("NOTIFY_REPEAT_ESCALATION_DAYS", "3"))
    except ValueError:
        configured = 3
    return max(1, configured)


def _dedup_notification(
    *,
    status: str,
    failed_steps: list[str],
    warnings: list[str],
    outcome: dict[str, object] | None,
    state_path: Path | None = None,
) -> bool:
    """Return True when a duplicate should be suppressed.

    A fingerprint is suppressed within a calendar day, but it is not allowed
    to disappear forever.  On the configured consecutive day (default: the
    third day) it is sent again as an escalation, then the recurrence counter
    starts a fresh cycle.
    """
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
    path = state_path or _notification_state_path()
    now_dt = _dedup_now()
    now = now_dt.timestamp()
    today = now_dt.date()
    try:
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        previous = {}
    try:
        window = max(0.0, float(os.environ.get("NOTIFY_DEDUP_WINDOW_S", str(24 * 3600))))
    except ValueError:
        window = float(24 * 3600)

    same_key = isinstance(previous, dict) and previous.get("key") == key
    should_suppress = False
    if same_key:
        previous_date: date | None = None
        raw_date = str(previous.get("last_seen_date") or "").strip()
        if raw_date:
            try:
                previous_date = date.fromisoformat(raw_date)
            except ValueError:
                previous_date = None
        if previous_date is None:
            try:
                previous_date = datetime.fromtimestamp(
                    float(previous.get("notified_at", 0) or 0), UTC
                ).date()
            except (TypeError, ValueError, OverflowError, OSError):
                previous_date = None

        if previous_date == today:
            should_suppress = True
            consecutive_days = int(previous.get("consecutive_days", 1) or 1)
        elif previous_date is not None and (today - previous_date).days == 1:
            consecutive_days = int(previous.get("consecutive_days", 1) or 1) + 1
            if consecutive_days < _repeat_escalation_days():
                should_suppress = True
            else:
                # Re-escalate now and begin a new consecutive-day cycle.
                consecutive_days = 0
                logger.warning(
                    "Re-escalating repeated notification fingerprint after %s consecutive days",
                    _repeat_escalation_days(),
                )
        elif previous_date is None and now - float(previous.get("notified_at", 0) or 0) < window:
            # Backward compatibility for the pre-counter state file.
            should_suppress = True
            consecutive_days = 1
        else:
            # A gap means this is a new recurrence, so notify immediately.
            consecutive_days = 1
    else:
        consecutive_days = 1

    state = {
        "key": key,
        "notified_at": now if not should_suppress else float(previous.get("notified_at", now) or now),
        "last_seen_date": today.isoformat(),
        "consecutive_days": consecutive_days,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        logger.warning("Unable to persist notification dedup state", exc_info=True)
    return should_suppress


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


def _notify_feishu(title: str, message: str) -> bool:
    """Send a text message to the configured Feishu bot webhook."""
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook_url or _suppression_reason():
        return False
    parsed = urlparse(webhook_url)
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme != "https"
        or host not in _FEISHU_HOSTS
        or parsed.query
        or parsed.fragment
    ):
        logger.warning("Feishu webhook skipped: invalid endpoint configuration")
        return False
    payload = json.dumps(
        {
            "msg_type": "text",
            "content": {"text": f"{redact_sink_text(title)}\n{redact_sink_text(message)}"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    endpoint = ExternalEndpointSpec(
        endpoint_id="feishu_webhook",
        url=webhook_url,
        allowed_hosts=frozenset({host}),
    )
    try:
        with OwnedExternalHTTPGateway({"feishu_webhook": endpoint}) as gateway:
            response = gateway.post(
                "feishu_webhook",
                payload,
                headers={"Content-Type": "application/json"},
                timeout_sec=TIMEOUT_SHORT,
            )
        return response.status_code < 400
    except (ExternalGatewayError, ValueError) as exc:
        logger.warning("Feishu webhook delivery failed: %s", type(exc).__name__)
        return False


def notify_feishu(title: str, message: str) -> bool:
    """Public, bounded Feishu sink used by summaries and dead-man alerts."""
    return _notify_feishu(title, message)


def _notify_telegram(title: str, message: str) -> bool:
    """Send a bounded text message to one configured Telegram private chat."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id or any(
        character in bot_token for character in "/?# \t\r\n"
    ):
        return False
    text = redact_sink_text(f"{title}\n{message}")
    if len(text) > _TELEGRAM_MAX_TEXT:
        text = text[: _TELEGRAM_MAX_TEXT - 3] + "..."
    endpoint = ExternalEndpointSpec(
        endpoint_id="telegram_bot",
        url=f"https://{_TELEGRAM_HOST}/bot{bot_token}/sendMessage",
        allowed_hosts=frozenset({_TELEGRAM_HOST}),
    )
    proxy_url = os.environ.get("TELEGRAM_HTTP_PROXY_URL", "").strip()
    gateway_kwargs = {"proxy_url": proxy_url} if proxy_url else {}
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        with OwnedExternalHTTPGateway(
            {"telegram_bot": endpoint}, **gateway_kwargs
        ) as gateway:
            response = gateway.post(
                "telegram_bot",
                payload,
                headers={"Content-Type": "application/json"},
                timeout_sec=TIMEOUT_SHORT,
            )
        return 200 <= response.status_code < 300
    except (ExternalGatewayError, ValueError) as exc:
        logger.warning("Telegram delivery failed: %s", type(exc).__name__)
        return False


def notify_telegram(title: str, message: str) -> bool:
    """Public, bounded Telegram sink used by summaries and dead-man alerts."""
    return _notify_telegram(title, message)


def _notify_primary_chat(title: str, message: str) -> bool:
    """Prefer Telegram private delivery; retain Feishu as a compatibility fallback."""
    if os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get(
        "TELEGRAM_CHAT_ID", ""
    ).strip():
        return _notify_telegram(title, message)
    return _notify_feishu(title, message)


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
    chat_ok = _notify_primary_chat(safe_title, safe_message)
    return desktop_ok or webhook_ok or chat_ok


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
    try:
        return notify_failure(title, preview, severity=severity)
    except TypeError as exc:
        # Keep small test doubles and older local integrations that still
        # expose notify_failure(title, message) compatible with the richer
        # observability signature.
        if "severity" not in str(exc):
            raise
        return notify_failure(title, preview)


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
    content_stale: list[str] | None = None,
    publish_blocked: str | None = None,
) -> None:
    """Notify hard failures while keeping known soft debt in the audit file."""
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
    hard: list[str] = [f"failed step: {step}" for step in failed_steps if step]
    for item in content_stale or []:
        text = str(item).strip()
        if text:
            hard.append(f"content stale: {text}")
    if publish_blocked:
        hard.append(f"publish blocked: {publish_blocked}")
    if status == "success" and not warnings and not outcome_failed and not hard:
        return
    outcome_degraded = bool(
        outcome
        and (
            outcome.get("status") == "degraded"
            or outcome.get("operational_state") == "COMPLETED_DEGRADED"
        )
    )
    if hard or outcome_failed:
        if outcome_degraded and not failed_steps:
            title = "System daily_run warnings"
            severity = "warning"
        else:
            title = "System daily_run failed"
            severity = "error"
        if _dedup_notification(
            status=status,
            failed_steps=[*failed_steps, *hard],
            warnings=warnings,
            outcome=outcome,
        ):
            logger.info("Suppressed duplicate daily-run notification")
            return
        notify_deviations(
            title,
            hard + ([f"outcome{outcome_suffix}"] if outcome_suffix else ["outcome=missing"]),
            severity=severity,
        )
        return
    # Warnings-only: log for local runs, never push.
    if warnings:
        print(
            f"NOTIFY[soft]: System daily_run warnings — "
            f"{'; '.join(str(w) for w in warnings[:4])}"
            f"{'; +…' if len(warnings) > 4 else ''} "
            f"(see Output/alerts/latest_alert.md)",
            file=sys.stderr,
        )


def notify_daily_run_summary(
    *,
    status: str,
    outcome: dict[str, object] | None = None,
    failed_steps: list[str] | None = None,
    warnings: list[str] | None = None,
) -> bool:
    """Send one compact Telegram summary for every completed daily run."""
    if _suppression_reason():
        return False
    outcome = outcome or {}
    failed = [str(item) for item in (failed_steps or []) if str(item).strip()]
    warning_items = [str(item) for item in (warnings or []) if str(item).strip()]
    lines = [
        f"status={status}",
        f"run_id={outcome.get('run_id') or 'unknown'}",
        f"exit_code={outcome.get('exit_code', 'unknown')}",
        f"publish={outcome.get('publish_status') or 'unknown'}",
    ]
    if failed:
        lines.append("failed_steps=" + ",".join(failed[:5]))
    if warning_items:
        lines.append("warnings=" + "; ".join(warning_items[:3]))
    return _notify_primary_chat("System daily_run 运行摘要", "\n".join(lines))


def notify_deadman_missing(*, reason: str, report: dict[str, object]) -> bool:
    """Send a deduplicated alert for a missing or stale daily heartbeat."""
    if _suppression_reason():
        return False
    output_root = _notification_state_path().parent.parent
    state_path = output_root / "health" / ".daily_run_deadman_notification.json"
    details = [f"reason={reason}"]
    if report.get("age_hours") is not None:
        details.append(f"age_hours={report.get('age_hours')}")
    details.append(f"max_age_hours={report.get('max_age_hours')}")
    outcome = {
        "run_id": "daily_run_deadman",
        "status": "deadman_alert",
        "exit_code": 1,
        "reason_codes": ["DAILY_RUN_HEARTBEAT_MISSING"],
    }
    if _dedup_notification(
        status="deadman_alert",
        failed_steps=["daily_run_heartbeat"],
        warnings=[reason],
        outcome=outcome,
        state_path=state_path,
    ):
        return False
    message = "; ".join(details)
    _notify_observability(
        "System daily_run dead-man switch",
        message,
        severity="error",
    )
    safe_title = "System daily_run dead-man switch"
    safe_message = redact_sink_text(message)
    desktop_ok = _notify_desktop(safe_title, safe_message)
    webhook_ok = _notify_webhook(safe_title, safe_message)
    chat_ok = _notify_primary_chat(safe_title, safe_message)
    return desktop_ok or webhook_ok or chat_ok
