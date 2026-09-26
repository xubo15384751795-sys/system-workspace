#!/usr/bin/env python3
"""Independent dead-man checker for the scheduled System daily run."""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from system_runtime.daily_heartbeat import (
    check_daily_run_heartbeat,
    default_output_root,
)
from verity.runtime.runtime_io import write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--max-age-hours", type=float)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    output_root = args.output_root or default_output_root()
    if args.output_root:
        os.environ["DAILY_OUTPUT_ROOT"] = str(output_root)
    report = check_daily_run_heartbeat(
        output_root=output_root,
        max_age_hours=args.max_age_hours,
    )
    report_path = output_root / "state" / "health" / "daily_run_deadman.json"
    write_json(report_path, report)

    if report.get("status") == "ALERT" and not args.dry_run:
        from verity.runtime._notify import notify_deadman_missing

        notified = notify_deadman_missing(
            reason=str(report.get("reason") or "heartbeat_invalid"),
            report=report,
        )
        report["notification"] = "sent" if notified else "suppressed_or_unavailable"
        report["notified_at"] = datetime.now(UTC).isoformat()
        write_json(report_path, report)

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if report.get("status") == "ALERT" else 0


if __name__ == "__main__":
    raise SystemExit(main())
