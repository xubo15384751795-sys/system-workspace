"""Dagster ops for the Output/current refresh chain."""
from __future__ import annotations

import time
from typing import cast

from dagster import In, Nothing, op

from scripts._admission_gate import admit_for_consumption
from orchestration.pipeline_runner import run_registry_step
from scripts._runtime_io import ROOT
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import CompiledStep, load_pipeline

REFRESH_PROFILE = "refresh_current"


def refresh_projection() -> tuple[CompiledStep, ...]:
    """Return the refresh projection from the canonical compiled plan."""
    plan = load_pipeline(WorkspacePaths(root=ROOT))
    return cast(tuple[CompiledStep, ...], plan.projection(REFRESH_PROFILE))


@op(name="refresh_admission")
def refresh_admission_op(context):
    start = time.time()
    decision = admit_for_consumption("refresh_current")
    result = {
        "step": "pre_consumption_admission",
        "status": "success" if decision.allowed else "blocked",
        "duration_s": round(time.time() - start, 1),
        "blockers": list(decision.blockers),
        "checked_at": decision.checked_at,
        "content_result_digests": list(decision.content_result_digests),
        "freshness_digest": decision.freshness_digest,
    }
    if result["status"] != "success":
        context.log.error("Refresh admission blocked: %s", result["blockers"])
        raise RuntimeError(f"refresh admission blocked: {result['blockers']}")
    return result


@op(
    name="refresh_producers",
    ins={"admission": In(Nothing)},
)
def refresh_producers_op(context, skip_measurement=False):
    steps = []
    for compiled_step in refresh_projection():
        if compiled_step.step_id == "neutral_pressure_measurement" and skip_measurement:
            context.log.info("Skipping %s", compiled_step.step_id)
            continue
        result = run_registry_step(compiled_step.step_id)
        steps.append(result)
        context.log.info("%s -> %s", compiled_step.step_id, result["status"])
        if result["status"] != "success":
            raise RuntimeError(f"refresh stopped after {compiled_step.step_id}")
    return {"steps": steps}
