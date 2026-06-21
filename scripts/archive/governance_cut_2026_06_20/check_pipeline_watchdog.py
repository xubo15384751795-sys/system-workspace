#!/usr/bin/env python3
"""Pipeline watchdog — verify the last successful run is recent.

Checks Output/current/framework_output.json modification time against
a configurable max-age threshold (default 24h). Exits non-zero and
sends a notification if the pipeline hasn't run recently.

Usage:
    python3 scripts/check_pipeline_watchdog.py
    python3 scripts/check_pipeline_watchdog.py --max-age-hours 48
    python3 scripts/check_pipeline_watchdog.py --json

Exit codes:
    0 — pipeline is fresh
    1 — pipeline is stale or missing
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from _workspace_imports import add_scripts  # noqa: E402
add_scripts()
from _runtime_io import ROOT

from _notify import notify_failure  # noqa: E402

FRAMEWORK_OUTPUT = ROOT / "Output" / "current" / "framework_output.json"
FRESHNESS_REPORT = ROOT / "Output" / "quality" / "freshness_report.json"


def check_pipeline_freshness(max_age_hours: float = 24.0) -> dict:
    """Check if the pipeline has run within the allowed window."""
    now = datetime.now(UTC)

    if not FRAMEWORK_OUTPUT.exists():
        return {
            "status": "MISSING",
            "message": "framework_output.json does not exist — pipeline has never run",
            "age_hours": None,
            "max_age_hours": max_age_hours,
        }

    mtime = datetime.fromtimestamp(FRAMEWORK_OUTPUT.stat().st_mtime, tz=UTC)
    age_hours = (now - mtime).total_seconds() / 3600

    if age_hours > max_age_hours:
        return {
            "status": "STALE",
            "message": f"Last pipeline run was {age_hours:.1f}h ago (max: {max_age_hours}h)",
            "age_hours": round(age_hours, 1),
            "max_age_hours": max_age_hours,
            "last_modified": mtime.isoformat(),
        }

    return {
        "status": "FRESH",
        "message": f"Pipeline ran {age_hours:.1f}h ago",
        "age_hours": round(age_hours, 1),
        "max_age_hours": max_age_hours,
        "last_modified": mtime.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=24.0,
        help="Maximum allowed age in hours (default: 24).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    result = check_pipeline_freshness(args.max_age_hours)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        icon = {"FRESH": "✅", "STALE": "🔴", "MISSING": "⚠️"}.get(result["status"], "?")
        print(f"{icon} Pipeline watchdog: {result['message']}")

    if result["status"] != "FRESH":
        notify_failure(
            "Pipeline watchdog alert",
            result["message"],
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
