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
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime

from scripts._constants import TIMEOUT_SHORT


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
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SHORT) as resp:
            return resp.status < 400
    except Exception:
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


def notify_failure(title: str, message: str) -> bool:
    """Show notification via all available channels. Returns True if any ran."""
    suppressed = _suppression_reason()
    if suppressed:
        # Still visible to whoever is running, just not as a desktop alert.
        print(f"NOTIFY[suppressed:{suppressed}]: {title} — {message}", file=sys.stderr)
        return False
    desktop_ok = _notify_desktop(title, message)
    webhook_ok = _notify_webhook(title, message)
    return desktop_ok or webhook_ok


def notify_alert(title: str, message: str) -> bool:
    """Risk / stance alert (same channels as notify_failure; neutral naming)."""
    return notify_failure(title, message)


def notify_deviations(title: str, deviations: list[str]) -> bool:
    """Notify only when deviations exist; normal state has zero output."""
    compact = [str(item).strip() for item in deviations if str(item).strip()]
    if not compact:
        return False
    preview = "; ".join(compact[:3])
    if len(compact) > 3:
        preview += f"; +{len(compact) - 3} more"
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
    content_stale: list[str] | None = None,
    publish_blocked: str | None = None,
) -> None:
    """Desktop/webhook push only for HARD failures, content STALE, or publish block.

    Soft failures (monitoring_coverage_audit, COVERAGE=ACTIVE_PARTIAL, etc.)
    stay in ``Output/alerts/latest_alert.md`` — they must not page the operator
    every nightly run. Content STALE / publish-block are merged into one HARD
    title so they do not fire a second "Content freshness STALE" notification.
    """
    hard: list[str] = [f"failed step: {step}" for step in failed_steps if step]
    for item in content_stale or []:
        text = str(item).strip()
        if text:
            hard.append(f"content stale: {text}")
    if publish_blocked:
        hard.append(f"publish blocked: {publish_blocked}")
    if hard:
        notify_deviations("System daily_run failed", hard)
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
