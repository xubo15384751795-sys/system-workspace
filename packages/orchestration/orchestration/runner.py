"""In-process entrypoints used by scripts/daily_run.py and refresh_output_current.py."""
from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, cast

from dagster import In, build_op_context, graph, op

from orchestration.canonical_lineage import attach_output_lineage
from orchestration.ops.refresh_chain import (
    refresh_admission_op,
    refresh_projection,
)
from orchestration.sequence_executor import (
    STEP_INPUT_ARTIFACTS,
    DailyRunContext,
    execute_daily_sequence,
    execute_step,
    should_run_step,
)
from scripts._daily_run_sequence import load_daily_run_sequence
from scripts._pipeline_runner import run_registry_step
from scripts._runtime_io import ROOT
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import CompiledPlan, load_pipeline

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
    plan: CompiledPlan | None = None


def _safe_node_name(prefix: str, value: str, index: int) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]", "_", value).strip("_") or "step"
    return f"{prefix}_{index:03d}_{normalized}"


def _step_input_name(producer: str, index: int) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]", "_", producer).strip("_") or "step"
    return f"upstream_{index:03d}_{normalized}"


def _current_code_sha() -> str:
    """Return the source revision attached to Dagster step metadata."""
    configured = os.environ.get("SYSTEM_CODE_SHA", "").strip()
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def build_daily_step_job(
    payload: DailyRunPayload, *, plan: CompiledPlan | None = None
):
    """Build a Dagster job with one op for every compiled daily step.

    The graph is deliberately generated from the compiled plan.  It does not
    maintain a second step list, dependency list, or failure-policy table.
    ``execute_in_process`` is used by the current daily entrypoint, while the
    graph itself gives Dagster a real per-step execution and metadata boundary.
    """
    resolved_plan = plan or payload.plan or load_pipeline(WorkspacePaths(root=ROOT))
    code_sha = _current_code_sha()
    sequence = resolved_plan.sequence()
    sequence_ids = [str(step_meta.get("id", "")) for step_meta in sequence]
    sequence_ids = [step_id for step_id in sequence_ids if step_id]
    execution_ctx = DailyRunContext(
        args=payload.args,
        start_time=payload.start_time,
        total_steps=payload.total_steps,
        run_step_fn=payload.run_step_fn,
        record_fn=payload.record_fn,
        benchmark_panel_path=payload.benchmark_panel_path,
        run_id=payload.run_id,
        plan=resolved_plan,
    )
    observed_results: list[dict[str, Any]] = []

    @graph(name="daily_compiled_plan_graph")
    def _daily_compiled_plan_graph():
        op_refs: dict[str, Any] = {}
        op_defs: list[Any] = []

        for index, step_id in enumerate(sequence_ids, start=1):
            compiled_step = resolved_plan.step(step_id)
            upstream_ids = [
                producer
                for producer in resolved_plan.edges.get(step_id, ())
                if producer in op_refs
            ]
            input_defs = {
                _step_input_name(producer, upstream_index): In(dict)
                for upstream_index, producer in enumerate(upstream_ids, start=1)
            }

            def _make_compute_step(
                current_step_id: str,
                current_index: int,
                current_step: Any,
                current_upstream_ids: tuple[str, ...],
            ):
                def _compute_step(context, **_upstream):
                    del _upstream
                    execution_ctx.step_index = current_index
                    step_meta = current_step.as_sequence_record()
                    run, reason = should_run_step(
                        current_step_id, step_meta, execution_ctx
                    )
                    context.log.info(
                        "compiled step=%s owner=%s plan_digest=%s run=%s reason=%s",
                        current_step_id,
                        current_step.owner,
                        resolved_plan.plan_digest,
                        run,
                        reason,
                    )
                    context.add_output_metadata(
                        {
                            "step_id": current_step_id,
                            "owner": current_step.owner,
                            "plan_digest": resolved_plan.plan_digest,
                            "code_sha": code_sha,
                            "bundle_run_id": payload.run_id,
                            "failure_behavior": current_step.failure_behavior,
                            "execution_mode": current_step.execution_mode,
                            "inputs": list(current_step.inputs),
                            "outputs": list(current_step.outputs),
                            "upstream_steps": list(current_upstream_ids),
                        }
                    )
                    if not run:
                        return {
                            "step": current_step_id,
                            "status": "skipped",
                            "skip_reason": reason,
                            "duration_s": 0,
                        }

                    decision = resolved_plan.interpret_failure(
                        current_step_id, observed_results
                    )
                    if decision["action"] == "block":
                        result = {
                            "step": current_step_id,
                            "status": "blocked_upstream",
                            "blocked_by": decision["blocked_by"],
                            "duration_s": 0,
                        }
                    else:
                        try:
                            result = execute_step(
                                current_step_id, execution_ctx, plan=resolved_plan
                            )
                        except ValueError as exc:
                            result = {
                                "step": current_step_id,
                                "status": "error",
                                "error": str(exc),
                                "duration_s": 0,
                            }
                        if decision.get("degraded") and result.get("status") == "success":
                            result["degraded"] = True
                            result["degraded_by"] = decision.get("degraded_by", [])

                    # Read-only shadow bridge.  The helper rejects stale or
                    # invalid output surfaces and never creates a lineage ID.
                    attach_output_lineage(
                        result,
                        current_step.outputs,
                        run_id=execution_ctx.run_id,
                    )

                    input_builder = STEP_INPUT_ARTIFACTS.get(current_step_id)
                    input_artifacts = (
                        input_builder(execution_ctx) if input_builder else None
                    )
                    execution_ctx.record_fn(result, input_artifacts=input_artifacts)
                    observed_results.append(result)
                    context.add_output_metadata(
                        {
                            "status": result.get("status", "unknown"),
                            "degraded": bool(result.get("degraded")),
                            "blocked_by": result.get("blocked_by", []),
                        }
                    )
                    return result

                return _compute_step

            step_op = op(
                name=_safe_node_name("daily_step", step_id, index),
                ins=input_defs,
            )(
                _make_compute_step(
                    step_id,
                    index,
                    compiled_step,
                    tuple(upstream_ids),
                )
            )
            op_defs.append(step_op)
            op_refs[step_id] = step_op(
                **{
                    _step_input_name(producer, upstream_index): op_refs[producer]
                    for upstream_index, producer in enumerate(upstream_ids, start=1)
                }
            )

        summary_inputs = {
            f"step_{index:03d}": In(dict) for index in range(1, len(op_defs) + 1)
        }

        @op(name="daily_compiled_plan_graph_summary", ins=summary_inputs)
        def _summary(context, **step_results):
            context.add_output_metadata(
                {
                    "plan_digest": resolved_plan.plan_digest,
                    "code_sha": code_sha,
                    "bundle_run_id": payload.run_id,
                    "step_count": len(step_results),
                    "recorded_result_count": len(observed_results),
                }
            )
            return {
                "step": "compiled_plan_summary",
                "status": "success",
                "plan_digest": resolved_plan.plan_digest,
                "step_count": len(step_results),
            }

        _summary(
            **{
                f"step_{index:03d}": op_refs[step_id]
                for index, step_id in enumerate(sequence_ids, start=1)
            }
        )

    return _daily_compiled_plan_graph.to_job(
        name="daily_compiled_plan_job",
        description="Dagster graph generated from the authoritative compiled daily plan.",
    )


def run_daily_sequence_via_dagster(payload: DailyRunPayload) -> list[dict[str, Any]]:
    """Default-path daily sequence: compiled per-step Dagster graph."""
    plan = payload.plan or load_pipeline(WorkspacePaths(root=ROOT))
    captured: list[dict[str, Any]] = []

    def _record(result: dict[str, Any], input_artifacts: list[str] | None = None) -> None:
        captured.append(result)
        payload.record_fn(result, input_artifacts=input_artifacts)

    job = build_daily_step_job(replace(payload, record_fn=_record, plan=plan), plan=plan)
    execution = job.execute_in_process()
    if not execution.success:
        raise RuntimeError(
            f"compiled daily Dagster job failed for run_id={payload.run_id} "
            f"(plan_digest={plan.plan_digest})"
        )
    return captured


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
        plan=payload.plan,
    )
    return cast(list[dict[str, Any]], execute_daily_sequence(ctx, plan=payload.plan))


def run_refresh_via_dagster(*, skip_measurement: bool = False, dry_run: bool = False) -> int:
    """Execute the refresh chain under Dagster ops (in-process)."""
    if dry_run:
        print("DRY RUN — Dagster refresh_current_job would execute:")
        print("  1. pre-consumption admission (hard gate)")
        index = 2
        for step in refresh_projection():
            if skip_measurement and step.step_id == "neutral_pressure_measurement":
                continue
            print(f"  {index}. {step.step_id} ({step.command or step.callable_spec})")
            index += 1
        return 0

    context = build_op_context()
    admission = refresh_admission_op(context)
    steps: list[dict[str, Any]] = [admission]
    for compiled_step in refresh_projection():
        if skip_measurement and compiled_step.step_id == "neutral_pressure_measurement":
            continue
        result = run_registry_step(compiled_step.step_id)
        steps.append(result)
        if result["status"] != "success":
            _print_refresh_summary(steps)
            print(f"\nRefresh stopped after blocking step: {compiled_step.step_id}.")
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


__all__ = [
    "DailyRunPayload",
    "build_daily_step_job",
    "run_daily_sequence_direct",
    "run_daily_sequence_via_dagster",
    "run_refresh_via_dagster",
    "sequence_length",
    "use_legacy_daily_run",
]
