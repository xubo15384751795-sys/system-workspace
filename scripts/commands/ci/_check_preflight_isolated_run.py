#!/usr/bin/env python3
"""Accept an isolated skip-harvester daily_run whose only failure is admission block."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ALLOWED_REASON_CODES = frozenset({"ADMISSION_REJECTED", "PUBLISH_NOT_COMMITTED"})
ROOT = Path("/tmp/verity-preflight/runs")


def main() -> int:
    runs = sorted(
        (path for path in ROOT.glob("daily_pipeline_*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
    )
    if not runs:
        print("preflight: no isolated run bundle under /tmp/verity-preflight/runs", file=sys.stderr)
        return 1
    outcome_path = runs[-1] / "run_outcome.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    failed = outcome.get("failed_steps") or []
    execution = str(outcome.get("execution_status") or "").upper()
    extra = [
        code for code in (outcome.get("reason_codes") or []) if code not in ALLOWED_REASON_CODES
    ]
    if failed or execution != "SUCCESS" or extra:
        print(
            "preflight: isolated daily_run not healthy "
            f"run_id={outcome.get('run_id')} execution={execution} "
            f"failed_steps={failed} extra_reason_codes={extra}",
            file=sys.stderr,
        )
        return 1
    print(
        f"isolated daily_run chain healthy ({runs[-1].name}); "
        "admission block is current baseline"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
