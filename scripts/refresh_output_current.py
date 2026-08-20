#!/usr/bin/env python3
"""Refresh Output/current — unified authority entry point.

Default path: Dagster ``refresh_current_job`` (in-process via orchestration.runner).
Emergency: ``SYSTEM_USE_LEGACY_DAILY_RUN=1`` restores the pre-Dagster linear chain.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime

from scripts._admission_gate import AdmissionDecision, admit_for_consumption
from scripts._pipeline_runner import (
    list_profile_steps,
    load_registry,
    run_registry_step,
)
from scripts._runtime_io import surface_dir

CURRENT = surface_dir("current")
JUDGMENT = surface_dir("judgment")


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
    profile_steps = list_profile_steps("refresh_current")
    total = len(profile_steps) + 1
    step_no = 1

    print(f"[{step_no}/{total}] Checking pre-consumption admission...")
    admission = run_refresh_admission()
    steps.append(admission)
    step_no += 1
    if admission["status"] != "success":
        _print_summary(steps, start_time)
        print("\nRefresh blocked before any producer or descendant was executed.")
        return 1

    def _run(step_id: str) -> bool:
        nonlocal step_no
        print(f"[{step_no}/{total}] {step_id}...")
        result = run_registry_step(step_id)
        steps.append(result)
        step_no += 1
        return result["status"] == "success"

    for step_id in profile_steps:
        if step_id == "neutral_pressure_measurement" and skip_measurement:
            print(f"[{step_no}/{total}] Skipping neutral measurement")
            step_no += 1
            continue
        if not _run(step_id):
            _print_summary(steps, start_time)
            print(f"\nRefresh stopped after blocking step: {step_id}.")
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
        surface_dir("quality") / "freshness_report.json",
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

    if legacy:
        if args.dry_run:
            print("DRY RUN — legacy refresh chain (explicit emergency flag)")
            return 0
        return _legacy_main(args)
    if args.dry_run:
        # A dry-run is an entrypoint wiring check; it must not import the
        # optional orchestration package or require a live Dagster workspace.
        print("DRY RUN — pre-consumption admission (hard gate); Dagster refresh chain")
        registry = load_registry()
        for step_id in list_profile_steps("refresh_current"):
            command = str((registry.get("steps", {}).get(step_id) or {}).get("command") or step_id)
            print(f"  {step_id}: {command}")
        return 0
    if not dagster_ok:
        print(
            "Dagster is unavailable; refresh default path is fail-closed. "
            "Use SYSTEM_USE_LEGACY_DAILY_RUN=1 only for an explicit emergency run.",
            file=sys.stderr,
        )
        return 78

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
