"""Desktop and remote notifications for pipeline failures.

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

from _constants import TIMEOUT_SHORT


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


def notify_failure(title: str, message: str) -> bool:
    """Show notification via all available channels. Returns True if any ran."""
    desktop_ok = _notify_desktop(title, message)
    webhook_ok = _notify_webhook(title, message)
    return desktop_ok or webhook_ok


def notify_alert(title: str, message: str) -> bool:
    """Risk / stance alert (same channels as notify_failure; neutral naming)."""
    return notify_failure(title, message)


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
) -> None:
    if status == "success" and not warnings:
        return
    if failed_steps:
        notify_failure(
            "System daily_run failed",
            f"{len(failed_steps)} step(s): {', '.join(failed_steps[:3])}",
        )
        return
    if warnings:
        notify_failure(
            "System daily_run warnings",
            f"{len(warnings)} warning(s); check Output/alerts/latest_alert.md",
        )
