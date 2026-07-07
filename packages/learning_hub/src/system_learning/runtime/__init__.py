"""Governance runtime: run context, paths, orchestration (no domain rules)."""

from system_learning.runtime.context import (
    GOVERNANCE_RULES_VERSION,
    SCHEMA_VERSION,
    SENSOR_VERSIONS,
    RunContext,
    new_run_context,
)
from system_learning.runtime.paths import HubPaths

__all__ = [
    "GOVERNANCE_RULES_VERSION",
    "SCHEMA_VERSION",
    "SENSOR_VERSIONS",
    "HubPaths",
    "RunContext",
    "new_run_context",
]


def __getattr__(name: str):
    if name in {"PipelinePlan", "PipelineResult", "execute_pipeline"}:
        from system_learning.runtime.pipeline import PipelinePlan, PipelineResult, execute_pipeline

        return {"PipelinePlan": PipelinePlan, "PipelineResult": PipelineResult, "execute_pipeline": execute_pipeline}[name]
    raise AttributeError(name)
