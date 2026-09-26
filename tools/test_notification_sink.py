#!/usr/bin/env python3
"""Send one deliberate Telegram text message for connectivity testing."""
from __future__ import annotations

import os
import sys

from system_runtime.runtime_secrets import load_runtime_secrets
from verity.runtime._notify import notify_telegram


def main() -> int:
    load_runtime_secrets()
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip():
        print("TELEGRAM_BOT_TOKEN is not configured", file=sys.stderr)
        return 2
    if not os.environ.get("TELEGRAM_CHAT_ID", "").strip():
        print("TELEGRAM_CHAT_ID is not configured", file=sys.stderr)
        return 2
    if not notify_telegram(
        "System Telegram connectivity test",
        "manual test message; daily summary/dead-man channel is reachable",
    ):
        print("Telegram delivery failed", file=sys.stderr)
        return 1
    print("Telegram message delivered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
