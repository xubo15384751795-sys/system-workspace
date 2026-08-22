#!/usr/bin/env python3
"""Send one deliberate Feishu text message for connectivity testing."""
from __future__ import annotations

import os
import sys

from scripts._notify import notify_feishu
from system_runtime.runtime_secrets import load_runtime_secrets


def main() -> int:
    load_runtime_secrets()
    if not os.environ.get("FEISHU_WEBHOOK_URL", "").strip():
        print("FEISHU_WEBHOOK_URL is not configured", file=sys.stderr)
        return 2
    if not notify_feishu(
        "System Feishu connectivity test",
        "manual test message; daily summary/dead-man channel is reachable",
    ):
        print("Feishu webhook delivery failed", file=sys.stderr)
        return 1
    print("Feishu webhook delivered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
