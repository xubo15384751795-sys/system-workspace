#!/usr/bin/env python3
"""Refresh Output/current — unified authority entry point.

Default path: Dagster ``refresh_current_job`` (in-process via orchestration.runner).
Emergency: ``SYSTEM_USE_LEGACY_DAILY_RUN=1`` restores the pre-Dagster linear chain.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure workspace + orchestration package are importable for ./sys refresh.
_ROOT_BOOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT_BOOT), str(_ROOT_BOOT / "scripts"), str(_ROOT_BOOT / "packages" / "orchestration")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts._admission_gate import AdmissionDecision, admit_for_consumption
from scripts._constants import TIMEOUT_STANDARD
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


def _legacy_main(args: argparse.Namespace) -> int:
    """Pre-Dagster linear chain retained for emergency escape hatch."""
    start_time = datetime.now(UTC)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Output/current with new judgment chain.")
    parser.add_argument("--skip-measurement", action="store_true", help="Skip neutral measurement step.")
    parser.add_argument("--skip-bridge", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="Print plan, don't execute.")
    args = parser.parse_args(argv)

    legacy = os.environ.get("SYSTEM_USE_LEGACY_DAILY_RUN", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }
    try:
        import dagster  # noqa: F401

        dagster_ok = True
    except ImportError:
        dagster_ok = False

    if legacy or not dagster_ok:
        if args.dry_run:
            print("DRY RUN — legacy refresh chain" + ("" if legacy else " (dagster not installed)"))
            return 0
        return _legacy_main(args)

    # Prefer orchestration.cli when SYSTEM_ORCHESTRATOR=dagster (aligned with launchd).
    if os.environ.get("SYSTEM_ORCHESTRATOR", "").strip().lower() == "dagster":
        from orchestration.cli import cmd_refresh

        refresh_argv: list[str] = []
        if args.skip_measurement or args.skip_bridge:
            refresh_argv.append("--skip-measurement")
        if args.dry_run:
            refresh_argv.append("--dry-run")
        return cmd_refresh(refresh_argv)

    from orchestration.runner import run_refresh_via_dagster

    return run_refresh_via_dagster(
        skip_measurement=bool(args.skip_measurement or args.skip_bridge),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
