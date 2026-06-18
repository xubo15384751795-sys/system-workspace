"""Desktop notifications for pipeline failures (macOS osascript)."""
from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any


def notify_failure(title: str, message: str) -> bool:
    """Show a desktop notification. Returns True if a notifier ran."""
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
            timeout=10,
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
