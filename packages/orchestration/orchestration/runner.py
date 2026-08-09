"""In-process entrypoints used by scripts/daily_run.py and refresh_output_current.py."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from dagster import ExecuteInProcessResult, build_op_context

from orchestration.ops.refresh_chain import (
    REFRESH_PRODUCER_STEPS,
    _run_script,
    refresh_admission_op,
)
from orchestration.ops.registry_step import execute_registry_sequence_op
from orchestration.sequence_executor import DailyRunContext, execute_daily_sequence
from scripts._daily_run_sequence import load_daily_run_sequence

logger = logging.getLogger(__name__)

LEGACY_ENV = "SYSTEM_USE_LEGACY_DAILY_RUN"


def use_legacy_daily_run() -> bool:
    return os.environ.get(LEGACY_ENV, "").strip() in {"1", "true", "TRUE", "yes", "YES"}


@dataclass
class DailyRunPayload:
    args: Any
    start_time: datetime
    total_steps: int
    run_step_fn: Callable[..., dict[str, Any]]
    record_fn: Callable[..., None]
    benchmark_panel_path: Path
    run_id: str = ""


def run_daily_sequence_via_dagster(payload: DailyRunPayload) -> list[dict[str, Any]]:
    """Default-path daily sequence: Dagster op executed in-process.

    Falls back to direct sequence_executor only when Dagster cannot import;
    emergency full legacy path is ``SYSTEM_USE_LEGACY_DAILY_RUN=1``.
    """
    op_payload = {
        "args": payload.args,
        "start_time": payload.start_time,
        "total_steps": payload.total_steps,
        "run_step_fn": payload.run_step_fn,
        "record_fn": payload.record_fn,
        "benchmark_panel_path": payload.benchmark_panel_path,
        "run_id": payload.run_id,
    }
    context = build_op_context()
    result = execute_registry_sequence_op(context, op_payload)
    return list(result.get("results") or [])


def run_daily_sequence_direct(payload: DailyRunPayload) -> list[dict[str, Any]]:
    """Direct executor path (also used by hermetic tests that skip Dagster)."""
    ctx = DailyRunContext(
        args=payload.args,
        start_time=payload.start_time,
        total_steps=payload.total_steps,
        run_step_fn=payload.run_step_fn,
        record_fn=payload.record_fn,
        benchmark_panel_path=payload.benchmark_panel_path,
        run_id=payload.run_id,
    )
    return execute_daily_sequence(ctx)


def run_refresh_via_dagster(*, skip_measurement: bool = False, dry_run: bool = False) -> int:
    """Execute the refresh chain under Dagster ops (in-process)."""
    if dry_run:
        print("DRY RUN — Dagster refresh_current_job would execute:")
        print("  1. pre-consumption admission (hard gate)")
        if not skip_measurement:
            print("  2. neutral_pressure_measurement.py")
        for index, (label, script) in enumerate(REFRESH_PRODUCER_STEPS, start=3):
            print(f"  {index}. {script} ({label})")
        return 0

    context = build_op_context()
    admission = refresh_admission_op(context)
    steps: list[dict[str, Any]] = [admission]
    if not skip_measurement:
        result = _run_script("neutral_pressure_measurement", "neutral_pressure_measurement.py")
        steps.append(result)
        if result["status"] != "success":
            _print_refresh_summary(steps)
            return 1
    for label, script in REFRESH_PRODUCER_STEPS:
        extra: tuple[str, ...] = ("--skip-if-unchanged",) if label == "run_event" else ()
        result = _run_script(label, script, *extra)
        steps.append(result)
        if result["status"] != "success":
            _print_refresh_summary(steps)
            print(f"\nRefresh stopped after blocking step: {label}.")
            return 1
    _print_refresh_summary(steps)
    return _verify_refresh_outputs()


def _print_refresh_summary(steps: list[dict[str, Any]]) -> None:
    print("\n=== Refresh Complete (Dagster) ===")
    for step in steps:
        icon = "✅" if step.get("status") == "success" else "❌"
        print(f"  {icon} {step.get('step')}: {step.get('status')} ({step.get('duration_s', 0)}s)")
        for blocker in step.get("blockers", []) or []:
            print(f"      blocker: {blocker}")


def _verify_refresh_outputs() -> int:
    from scripts._runtime_io import ROOT

    current = ROOT / "Output" / "current"
    judgment = ROOT / "Output" / "judgment"
    required = [
        current / "neutral_pressure_snapshot.json",
        current / "framework_output.json",
        current / "measurement_quality.json",
        current / "signal_card.json",
        current / "signal_card.md",
        current / "signal_consensus.json",
        current / "signal_consensus.md",
        current / "00_READ_ME_FIRST.md",
        current / "status.json",
        current / "work_brief.json",
        current / "work_brief.md",
        current / "NEXT_ACTIONS.md",
        current / "evidence_grade_report.json",
        current / "artifact_registry.json",
        ROOT / "Output" / "quality" / "freshness_report.json",
        judgment / "latest.json",
        judgment / "latest.md",
        judgment / "promotion_gate.json",
        judgment / "promotion_gate.md",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        print(f"\nWARNING: Missing outputs: {[str(p) for p in missing]}")
        return 1
    print("\nAll outputs verified.")
    return 0


def sequence_length() -> int:
    return len(load_daily_run_sequence()) or 33
