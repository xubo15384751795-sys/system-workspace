#!/usr/bin/env python3
"""Workspace wrapper — append one runtime record via System Learning Hub."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB_SRC = ROOT / "system-learning-hub" / "src"
if str(HUB_SRC) not in sys.path:
    sys.path.insert(0, str(HUB_SRC))

from system_learning.runtime.record import append_runtime_record  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a runtime record to the Learning Hub log.")
    parser.add_argument("--system-root", type=Path, default=ROOT)
    parser.add_argument("--subsystem", required=True)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--severity", default="info")
    parser.add_argument("--source-tool", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--payload-json", default="{}")
    args = parser.parse_args()

    try:
        extra = json.loads(args.payload_json)
    except json.JSONDecodeError as exc:
        print(f"Invalid --payload-json: {exc}", file=sys.stderr)
        return 1
    if not isinstance(extra, dict):
        print("--payload-json must decode to an object", file=sys.stderr)
        return 1

    record = {
        "subsystem": args.subsystem,
        "event_type": args.event_type,
        "severity": args.severity,
        "source_tool": args.source_tool or args.subsystem,
        "run_id": args.run_id,
        **extra,
    }
    path = append_runtime_record(args.system_root.resolve(), record)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
