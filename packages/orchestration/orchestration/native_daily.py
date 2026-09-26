"""Compile the scheduled plan into a reversible Dagster asset graph.

This is the next Wave 4 seam after the small registry-tagged pilots.  The
compiled pipeline remains the only source of step order, data edges, and
failure behavior; this module only changes the Dagster execution primitive
from generated ``op`` nodes to native assets.  It is opt-in until a bounded
dual-run window proves parity with ``runner.py``.

The current registry still has side-effectful shared surfaces.  Therefore the
graph keeps the generated sequence barrier in addition to semantic upstream
edges.  The barrier is a rollback-safe scheduling guard, not a second DAG
authority.  Step implementations, publication, and ``steps.jsonl`` recording
remain unchanged while the asset graph is observed.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from typing import Any

from dagster import (
    AssetKey,
    AssetsDefinition,
    RetryPolicy,
    RetryRequested,
    asset,
    materialize,
)

from orchestration.canonical_lineage import attach_output_lineage
from orchestration.native_file_boundaries import (
    NATIVE_FILE_BOUNDARY_STEPS,
    execute_native_file_boundary,
)
from orchestration.native_core_boundaries import (
    NATIVE_CORE_BOUNDARY_STEPS,
    execute_native_core_boundary,
)
from orchestration.native_daily_checks import build_native_daily_checks
from orchestration.sequence_executor import (
    STEP_INPUT_ARTIFACTS,
    DailyRunContext,
    execute_step,
    should_run_step,
)
from verity.runtime.runtime_io import ROOT, current_dir
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import CompiledPlan, load_pipeline

NATIVE_DAILY_PREFIX = "native_daily"
NATIVE_DAILY_RETRY_POLICY = RetryPolicy(max_retries=1, delay=5)
NATIVE_DAILY_ENV = "SYSTEM_USE_NATIVE_DAILY_ASSETS"
NATIVE_FILE_BOUNDARY_ENV = "SYSTEM_USE_NATIVE_FILE_BOUNDARIES"
NATIVE_CORE_BOUNDARY_ENV = "SYSTEM_USE_NATIVE_CORE_BOUNDARIES"
_RETRYABLE_RESULT_STATUSES = frozenset({"failed", "error", "timeout"})


def use_native_daily_assets() -> bool:
    """Return whether the opt-in native asset graph is requested."""
    return os.environ.get(NATIVE_DAILY_ENV, "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }


def use_native_file_boundaries() -> bool:
    """Return whether explicitly migrated current-surface writers are active."""
    return os.environ.get(NATIVE_FILE_BOUNDARY_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def use_native_core_boundaries() -> bool:
    """Return whether core-judgment shadow writers are explicitly requested."""
    return os.environ.get(NATIVE_CORE_BOUNDARY_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _request_result_retry(context: Any, result: Mapping[str, Any]) -> None:
    """Turn a runner-style failed result into a real Dagster retry.

    The legacy runner reports subprocess/callable failures as dictionaries
    rather than exceptions.  A Dagster ``RetryPolicy`` only applies when the
    asset raises, so silently returning that dictionary would make the native
    graph claim to have retries while never using them.  Record the final
    failure normally after the retry budget is exhausted; transient attempts
    are represented by Dagster's event log instead of duplicate ``steps.jsonl``
    rows.
    """
    status = str(result.get("status") or "").lower()
    if status not in _RETRYABLE_RESULT_STATUSES:
        return
    retry_number = int(getattr(context, "retry_number", 0) or 0)
    max_retries = NATIVE_DAILY_RETRY_POLICY.max_retries
    if max_retries is None or retry_number < max_retries:
        raise RetryRequested(
            max_retries=max_retries,
            seconds_to_wait=NATIVE_DAILY_RETRY_POLICY.delay,
        )


def _safe_asset_name(step_id: str, index: int) -> str:
    normalized = re.sub(r"[^0-9A-Za-z_]", "_", step_id).strip("_") or "step"
    return f"daily_step_{index:03d}_{normalized}"


def _asset_key(step_id: str, index: int) -> AssetKey:
    return AssetKey([NATIVE_DAILY_PREFIX, _safe_asset_name(step_id, index)])


def build_native_daily_assets(
    payload: Any,
    *,
    plan: CompiledPlan | None = None,
) -> tuple[AssetsDefinition, ...]:
    """Build one native asset per active compiled-plan sequence step.

    The asset closures intentionally call the existing step implementation;
    this migration replaces orchestration mechanics, not H41/CFTC/parser or
    other step business logic.  The previous sequence step is included as a
    native dependency until shared ``Output/current`` writers are themselves
    migrated to file-level assets.
    """
    resolved_plan = plan or payload.plan or load_pipeline(WorkspacePaths(root=ROOT))
    sequence = resolved_plan.sequence()
    sequence_ids = [str(step_meta.get("id", "")) for step_meta in sequence if step_meta.get("id")]
    sequence_set = set(sequence_ids)
    execution_ctx = DailyRunContext(
        args=payload.args,
        start_time=payload.start_time,
        total_steps=payload.total_steps,
        run_step_fn=payload.run_step_fn,
        record_fn=payload.record_fn,
        benchmark_panel_path=payload.benchmark_panel_path,
        run_id=payload.run_id,
        plan=resolved_plan,
        dry_run=payload.dry_run,
    )
    observed_results: list[dict[str, Any]] = []
    assets: list[AssetsDefinition] = []

    for index, step_id in enumerate(sequence_ids, start=1):
        compiled_step = resolved_plan.step(step_id)
        semantic_upstream_ids = tuple(
            producer
            for producer in resolved_plan.edges.get(step_id, ())
            if producer in sequence_set
        )
        execution_upstream_ids = list(semantic_upstream_ids)
        if index > 1:
            previous_step = sequence_ids[index - 2]
            if previous_step not in execution_upstream_ids:
                execution_upstream_ids.append(previous_step)
        dependency_keys = tuple(
            _asset_key(producer, sequence_ids.index(producer) + 1)
            for producer in execution_upstream_ids
        )
        asset_name = _safe_asset_name(step_id, index)

        def _make_asset(
            current_step_id: str,
            current_index: int,
            current_step: Any,
            current_semantic_upstream_ids: tuple[str, ...],
            current_execution_upstream_ids: tuple[str, ...],
            current_dependency_keys: tuple[AssetKey, ...],
            current_asset_name: str,
        ) -> AssetsDefinition:
            file_boundary_requested = (
                use_native_file_boundaries()
                and current_step_id in NATIVE_FILE_BOUNDARY_STEPS
            )
            core_boundary_requested = (
                use_native_core_boundaries()
                and current_step_id in NATIVE_CORE_BOUNDARY_STEPS
            )
            @asset(
                name=current_asset_name,
                key_prefix=[NATIVE_DAILY_PREFIX],
                deps=list(current_dependency_keys),
                compute_kind="dagster_native_daily_asset",
                retry_policy=NATIVE_DAILY_RETRY_POLICY,
                metadata={
                    "step_id": current_step_id,
                    "plan_digest": resolved_plan.plan_digest,
                    "authority": "shadow_only",
                    "migration_batch": "wave4-native-daily-assets-opt-in",
                    "failure_behavior": current_step.failure_behavior,
                    "upstream_steps": list(current_semantic_upstream_ids),
                    "execution_upstream_steps": list(current_execution_upstream_ids),
                    "file_boundary": file_boundary_requested,
                    "core_boundary": core_boundary_requested,
                    "writes_legacy_output": (
                        not payload.dry_run
                        and not file_boundary_requested
                        and not core_boundary_requested
                    ),
                    "writes_active_generation": (
                        (file_boundary_requested or core_boundary_requested)
                        and not payload.dry_run
                    ),
                    "dry_run": payload.dry_run,
                },
            )
            def _native_daily_asset(context) -> dict[str, Any]:
                execution_ctx.step_index = current_index
                step_meta = current_step.as_sequence_record()
                run, reason = should_run_step(current_step_id, step_meta, execution_ctx)
                context.log.info(
                    "native asset step=%s plan_digest=%s run=%s reason=%s",
                    current_step_id,
                    resolved_plan.plan_digest,
                    run,
                    reason,
                )
                context.add_output_metadata(
                    {
                        "step_id": current_step_id,
                        "plan_digest": resolved_plan.plan_digest,
                        "failure_behavior": current_step.failure_behavior,
                        "upstream_steps": list(current_semantic_upstream_ids),
                        "execution_upstream_steps": list(current_execution_upstream_ids),
                        "authority": "shadow_only",
                        "dry_run": payload.dry_run,
                        "file_boundary": file_boundary_requested,
                        "core_boundary": core_boundary_requested,
                    }
                )
                if not run:
                    return {
                        "step": current_step_id,
                        "status": "skipped",
                        "skip_reason": reason,
                        "duration_s": 0,
                    }

                decision = resolved_plan.interpret_failure(current_step_id, observed_results)
                if decision["action"] == "block":
                    result: dict[str, Any] = {
                        "step": current_step_id,
                        "status": "blocked_upstream",
                        "blocked_by": decision["blocked_by"],
                        "duration_s": 0,
                    }
                else:
                    try:
                        if core_boundary_requested and not payload.dry_run:
                            result = execute_native_core_boundary(
                                current_step_id,
                                benchmark_panel_path=execution_ctx.benchmark_panel_path,
                                current_output=current_dir(),
                            )
                        elif file_boundary_requested and not payload.dry_run:
                            result = execute_native_file_boundary(current_step_id)
                        else:
                            result = execute_step(
                                current_step_id,
                                execution_ctx,
                                plan=resolved_plan,
                            )
                    except ValueError as exc:
                        result = {
                            "step": current_step_id,
                            "status": "error",
                            "error": str(exc),
                            "duration_s": 0,
                        }
                    _request_result_retry(context, result)
                    if decision.get("degraded") and result.get("status") == "success":
                        result["degraded"] = True
                        result["degraded_by"] = decision.get("degraded_by", [])

                attach_output_lineage(
                    result,
                    current_step.outputs,
                    run_id=execution_ctx.run_id,
                )
                input_builder: Callable[[Any], list[str]] | None = STEP_INPUT_ARTIFACTS.get(
                    current_step_id
                )
                input_artifacts = input_builder(execution_ctx) if input_builder else None
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

            return _native_daily_asset

        assets.append(
            _make_asset(
                step_id,
                index,
                compiled_step,
                semantic_upstream_ids,
                tuple(execution_upstream_ids),
                dependency_keys,
                asset_name,
            )
        )

    return tuple(assets)


def run_daily_sequence_via_native_assets(payload: Any) -> list[dict[str, Any]]:
    """Execute the opt-in native graph and return the recorded step results."""
    plan = payload.plan or load_pipeline(WorkspacePaths(root=ROOT))
    captured: list[dict[str, Any]] = []

    def _record(result: dict[str, Any], input_artifacts: list[str] | None = None) -> None:
        captured.append(result)
        payload.record_fn(result, input_artifacts=input_artifacts)

    from dataclasses import replace

    native_payload = replace(payload, record_fn=_record, plan=plan)
    assets = build_native_daily_assets(native_payload, plan=plan)
    # Checks are deliberately non-blocking during the opt-in observation
    # phase.  The result still flows through the existing failure_behavior
    # interpreter and ``steps.jsonl`` callback, while Dagster records a
    # first-class check event that the dual-track comparator can inspect.
    checks = build_native_daily_checks(assets, blocking=False)
    execution = materialize([*assets, *checks], raise_on_error=False)
    if not execution.success:
        raise RuntimeError(
            f"native daily asset graph failed for run_id={payload.run_id} "
            f"(plan_digest={plan.plan_digest})"
        )
    return captured


__all__ = [
    "NATIVE_DAILY_ENV",
    "NATIVE_FILE_BOUNDARY_ENV",
    "NATIVE_CORE_BOUNDARY_ENV",
    "NATIVE_DAILY_PREFIX",
    "build_native_daily_assets",
    "run_daily_sequence_via_native_assets",
    "use_native_file_boundaries",
    "use_native_core_boundaries",
    "use_native_daily_assets",
]
