#!/usr/bin/env python3
"""Refresh Output/current — unified authority entry point.

This is the ONLY script that should refresh Output/current/.
It runs the new judgment chain, not the old Workbench fallback.

The chain begins with a hard pre-consumption admission check. If admission or
any producer fails, descendants are not executed.

Usage:
    python3 scripts/refresh_output_current.py
    python3 scripts/refresh_output_current.py --skip-measurement
    python3 scripts/refresh_output_current.py --dry-run

Output:
    Output/current/neutral_pressure_snapshot.json
    Output/current/00_READ_ME_FIRST.md
    Output/judgment/latest.json
    Output/judgment/latest.md
    Output/judgment/promotion_gate.json
    Output/judgment/promotion_gate.md
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import UTC, datetime

from scripts._admission_gate import AdmissionDecision, admit_for_consumption
from scripts._constants import TIMEOUT_STANDARD  # noqa: E402
from scripts._runtime_io import ROOT

CURRENT = ROOT / "Output" / "current"
JUDGMENT = ROOT / "Output" / "judgment"


def run_step(name: str, cmd: list[str]) -> dict:
    """Run a subprocess and capture result."""
    start = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT_STANDARD,
            cwd=str(ROOT),
        )
        duration = time.time() - start
        return {
            "step": name,
            "status": "success" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "duration_s": round(duration, 1),
            "stdout_tail": result.stdout[-300:] if result.stdout else "",
            "stderr_tail": result.stderr[-300:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": name, "status": "timeout", "duration_s": 120}
    except Exception as e:
        return {"step": name, "status": "error", "error": str(e), "duration_s": 0}


def run_refresh_admission() -> dict:
    """Run the mandatory public-data admission check for the refresh chain."""
    start = time.time()
    decision: AdmissionDecision = admit_for_consumption("refresh_current")
    return {
        "step": "pre_consumption_admission",
        "status": "success" if decision.allowed else "blocked",
        "duration_s": round(time.time() - start, 1),
        "blockers": list(decision.blockers),
        "checked_at": decision.checked_at,
    }


def _print_summary(steps: list[dict], start_time: datetime) -> None:
    duration = (datetime.now(UTC) - start_time).total_seconds()
    print(f"\n=== Refresh Complete ({duration:.1f}s) ===")
    for step in steps:
        icon = "✅" if step["status"] == "success" else "❌"
        print(f"  {icon} {step['step']}: {step['status']} ({step['duration_s']}s)")
        for blocker in step.get("blockers", []):
            print(f"      blocker: {blocker}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Output/current with new judgment chain.")
    parser.add_argument("--skip-measurement", action="store_true", help="Skip neutral measurement step.")
    parser.add_argument("--skip-bridge", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="Print plan, don't execute.")
    args = parser.parse_args(argv)

    start_time = datetime.now(UTC)

    if args.dry_run:
        print("DRY RUN — would execute:")
        print("  1. pre-consumption admission (hard gate)")
        if not (args.skip_measurement or args.skip_bridge):
            print("  2. neutral_pressure_measurement.py")
        print("  3. quality_field_validator.py")
        print("  4. build_measurement_quality_report.py")
        print("  5. judgment_layer.py")
        print("  6. judgment_promotion_gate.py")
        print("  7. trade_decision_layer.py")
        print("  8. build_signal_card.py")
        print("  9. signal_consensus.py")
        print("  10. build_current_status.py")
        print("  11. build_system_index.py")
        print("  12. build_work_brief.py")
        print("  13. build_next_actions.py")
        print("  14. refresh_improvement_queue_report.py")
        print("  15. freshness_validator.py")
        print("  16. build_evidence_grade_report.py")
        print("  17. build_artifact_registry.py")
        print("  18. record_daily_run_event.py")
        print("  19. build_readme_first.py")
        return 0

    steps: list[dict] = []
    skip_measurement = args.skip_measurement or args.skip_bridge
    total = 19
    step_no = 1

    print(f"[{step_no}/{total}] Checking pre-consumption admission...")
    admission = run_refresh_admission()
    steps.append(admission)
    step_no += 1
    if admission["status"] != "success":
        _print_summary(steps, start_time)
        print("\nRefresh blocked before any producer or descendant was executed.")
        return 1

    def _run(label: str, script: str, *extra_args: str) -> bool:
        nonlocal step_no
        print(f"[{step_no}/{total}] {label}...")
        result = run_step(
            label,
            [sys.executable, str(ROOT / "scripts" / script), *extra_args],
        )
        steps.append(result)
        step_no += 1
        return result["status"] == "success"

    # Active theory-independent measurement (unless explicitly skipped).
    if not skip_measurement:
        if not _run("neutral_pressure_measurement", "neutral_pressure_measurement.py"):
            _print_summary(steps, start_time)
            return 1
    else:
        print(f"[{step_no}/{total}] Skipping neutral measurement")
        step_no += 1

    producer_steps = [
        ("quality_validation", "quality_field_validator.py"),
        ("measurement_quality", "commands/weekly/build_measurement_quality_report.py"),
        ("judgment_layer", "judgment_layer.py"),
        ("promotion_gate", "judgment_promotion_gate.py"),
        ("trade_decision", "trade_decision_layer.py"),
        ("signal_card", "build_signal_card.py"),
        ("signal_consensus", "signal_consensus.py"),
        ("current_status", "build_current_status.py"),
        ("system_index", "build_system_index.py"),
        ("work_brief", "build_work_brief.py"),
        ("next_actions", "commands/weekly/build_next_actions.py"),
        ("improvement_queue_report", "refresh_improvement_queue_report.py"),
        ("freshness_validator", "freshness_validator.py"),
        ("evidence_grade", "commands/weekly/build_evidence_grade_report.py"),
        ("artifact_registry", "commands/weekly/build_artifact_registry.py"),
    ]
    for label, script in producer_steps:
        if not _run(label, script):
            _print_summary(steps, start_time)
            print(f"\nRefresh stopped after blocking step: {label}.")
            return 1

    print(f"[{step_no}/{total}] Recording run event...")
    run_event = run_step(
        "run_event",
        [sys.executable, str(ROOT / "scripts" / "record_daily_run_event.py"), "--skip-if-unchanged"],
    )
    steps.append(run_event)
    step_no += 1
    if run_event["status"] != "success":
        _print_summary(steps, start_time)
        print("\nRefresh stopped after blocking step: run_event.")
        return 1
    if not _run("readme_first", "commands/weekly/build_readme_first.py"):
        _print_summary(steps, start_time)
        return 1

    _print_summary(steps, start_time)

    # Verify outputs exist
    required = [
        CURRENT / "neutral_pressure_snapshot.json",
        CURRENT / "framework_output.json",
        CURRENT / "measurement_quality.json",
        CURRENT / "signal_card.json",
        CURRENT / "signal_card.md",
        CURRENT / "signal_consensus.json",
        CURRENT / "signal_consensus.md",
        CURRENT / "00_READ_ME_FIRST.md",
        CURRENT / "status.json",
        CURRENT / "work_brief.json",
        CURRENT / "work_brief.md",
        CURRENT / "NEXT_ACTIONS.md",
        CURRENT / "evidence_grade_report.json",
        CURRENT / "artifact_registry.json",
        ROOT / "Output" / "quality" / "freshness_report.json",
        JUDGMENT / "latest.json",
        JUDGMENT / "latest.md",
        JUDGMENT / "promotion_gate.json",
        JUDGMENT / "promotion_gate.md",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        print(f"\nWARNING: Missing outputs: {[str(p) for p in missing]}")
        return 1

    print("\nAll outputs verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
