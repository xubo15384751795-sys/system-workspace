#!/usr/bin/env python3
"""Send one deliberate, sanitized Sentry exception for connectivity testing."""
from __future__ import annotations

import argparse
import os
import sys

from system_runtime.observability import capture_exception, init_sentry
from system_runtime.runtime_secrets import load_runtime_secrets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--message",
        default="manual System Sentry connectivity test",
        help="non-sensitive test message",
    )
    parser.add_argument("--flush-timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    load_runtime_secrets()
    if not os.environ.get("SENTRY_DSN", "").strip():
        print("SENTRY_DSN is not configured", file=sys.stderr)
        return 2
    if not init_sentry():
        print("Sentry initialization failed", file=sys.stderr)
        return 2

    try:
        raise RuntimeError(args.message)
    except RuntimeError as exc:
        capture_exception(exc)

    import sentry_sdk

    sentry_sdk.flush(timeout=max(1.0, min(float(args.flush_timeout), 60.0)))
    event_id = sentry_sdk.last_event_id()
    if not event_id:
        print("Sentry did not produce an event id", file=sys.stderr)
        return 1
    print(f"Sentry event flushed: {event_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
