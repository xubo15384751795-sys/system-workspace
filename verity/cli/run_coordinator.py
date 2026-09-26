"""Compiled-plan step coordination for the daily application.

This module owns the step execution adapter. It does not own publication,
provider semantics, or authority decisions.
"""
from __future__ import annotations

import os

from orchestration.pipeline_runner import (
    run_callable_step,
    run_registry_step,
)
from orchestration.pipeline_runner import (
    run_subprocess_step as _run_subprocess_step,
)

from system_runtime.pipeline import CompiledPlan, load_pipeline
from verity.runtime.runtime_io import ROOT

_PIPELINE_MODE = os.environ.get("DAILY_RUN_EXECUTION_MODE", "auto")


def set_pipeline_execution_mode(mode: str) -> None:
    """Set the explicit compatibility override for this process."""
    global _PIPELINE_MODE
    _PIPELINE_MODE = mode


def _resolve_execution_mode(step_id: str, *, plan: CompiledPlan | None = None) -> str:
    if _PIPELINE_MODE == "callable":
        return "callable"
    if _PIPELINE_MODE == "auto":
        from system_runtime.paths import WorkspacePaths

        # The compiled plan is the only production source of step execution
        # metadata. Unknown compatibility names remain subprocess steps.
        plan = plan or load_pipeline(WorkspacePaths(root=ROOT))
        try:
            return plan.step(step_id).execution_mode
        except KeyError:
            return "subprocess"
    return "subprocess"


def run_step(
    name: str,
    cmd: list[str],
    env: dict | None = None,
    *,
    registry_step: str | None = None,
    compiled_plan: CompiledPlan | None = None,
) -> dict:
    """Run one compiled step through callable or justified subprocess mode."""
    step_id = registry_step or name
    mode = _resolve_execution_mode(step_id, plan=compiled_plan)
    if mode == "callable":
        argv = cmd[2:] if len(cmd) > 2 and str(cmd[1]).endswith(".py") else cmd[1:]
        if compiled_plan is not None:
            compiled_step = compiled_plan.step(step_id)
            if not compiled_step.callable_spec:
                raise ValueError(f"{step_id} missing execution.future_callable")
            return run_callable_step(step_id, compiled_step.callable_spec, argv=argv)
        return run_registry_step(step_id, mode="callable", argv=argv)

    from system_runtime.paths import WorkspacePaths

    plan = compiled_plan or load_pipeline(WorkspacePaths(root=ROOT))
    try:
        compiled_step = plan.step(step_id)
    except KeyError:
        return _run_subprocess_step(name, cmd, env)
    return _run_subprocess_step(
        name,
        cmd,
        env,
        timeout=compiled_step.timeout_seconds,
        subprocess_justification=compiled_step.subprocess_justification,
    )
