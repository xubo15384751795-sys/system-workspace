"""Compile tagged registry steps into shadow Dagster assets.

The registry remains the authority for step order and failure_behavior.
These assets wrap ``run_registry_step`` and are not part of ``daily_job``.
They do not append to the daily ``steps.jsonl``; launchd remains the
publication record. Only ``continue_with_warning`` steps that cannot affect
core judgment may be tagged ``execution.dagster_asset: shadow_pilot``.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml
from dagster import AssetsDefinition, asset

from orchestration.shadow_parity import ShadowParityReport, compare_sequence_results

from scripts._runtime_io import ROOT

SHADOW_PILOT = "shadow_pilot"
ALLOWED_FAILURE_BEHAVIORS = frozenset({"continue_with_warning"})
_PARITY_FIELDS = (
    "status",
    "blocked_by",
    "degraded",
    "degraded_by",
    "skip_reason",
    "error",
)
RunStep = Callable[..., dict[str, Any]]


def load_registry_document(root: Path | None = None) -> dict[str, Any]:
    path = (root or ROOT) / "governance" / "daily_pipeline_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("pipeline registry must be a mapping")
    return payload


def select_shadow_pilot_steps(document: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Return tagged steps, or raise if a tag violates the shadow-pilot gate."""
    steps = document.get("steps") or {}
    selected: list[dict[str, str]] = []
    errors: list[str] = []
    if not isinstance(steps, dict):
        raise ValueError("pipeline registry steps must be a mapping")
    for step_id, spec in steps.items():
        if not isinstance(spec, dict):
            continue
        execution = spec.get("execution") or {}
        if not isinstance(execution, dict) or execution.get("dagster_asset") != SHADOW_PILOT:
            continue
        authority = spec.get("authority") if isinstance(spec.get("authority"), dict) else {}
        failure_behavior = str(
            spec.get("failure_behavior") or authority.get("failure_behavior") or ""
        )
        affects_core = bool(
            spec.get("allowed_to_affect_core_judgment")
            or authority.get("affects_core_judgment")
        )
        status = str(spec.get("status") or "")
        if status != "active":
            errors.append(f"{step_id}: shadow_pilot requires status=active")
        if failure_behavior not in ALLOWED_FAILURE_BEHAVIORS:
            errors.append(
                f"{step_id}: shadow_pilot forbids failure_behavior={failure_behavior!r}"
            )
        if affects_core:
            errors.append(f"{step_id}: shadow_pilot forbids core-judgment steps")
        selected.append({"step_id": str(step_id), "failure_behavior": failure_behavior})
    if errors:
        raise ValueError("invalid registry shadow_pilot tags: " + "; ".join(errors))
    return tuple(selected)


def shadow_step_payload(
    step_id: str,
    failure_behavior: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep runner semantics that shadow_parity compares; mark authority as shadow."""
    payload: dict[str, Any] = {
        "step": step_id,
        "step_id": step_id,
        "failure_behavior": failure_behavior,
        "authority": "shadow_only",
    }
    for field in _PARITY_FIELDS:
        if field in result:
            payload[field] = result[field]
        elif field == "status":
            payload[field] = None
    return payload


def compare_shadow_step(
    registry_result: Mapping[str, Any],
    asset_result: Mapping[str, Any],
    *,
    plan_digest: str | None = None,
) -> ShadowParityReport:
    """Compare one registry-runner result with its shadow-asset payload."""
    return compare_sequence_results(
        [registry_result],
        [asset_result],
        plan_digest=plan_digest,
    )


def _build_asset(step_id: str, failure_behavior: str, run_step: RunStep) -> AssetsDefinition:
    @asset(
        name=step_id,
        key_prefix=["registry_shadow"],
        compute_kind="registry_shadow",
        metadata={
            "step_id": step_id,
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
        },
    )
    def _registry_shadow_step() -> dict[str, Any]:
        return shadow_step_payload(step_id, failure_behavior, run_step(step_id))

    return _registry_shadow_step


def build_shadow_registry_assets(
    *,
    document: Mapping[str, Any] | None = None,
    run_step: RunStep | None = None,
) -> tuple[AssetsDefinition, ...]:
    from orchestration.pipeline_runner import run_registry_step

    selected = select_shadow_pilot_steps(document or load_registry_document())
    runner = run_step or run_registry_step
    return tuple(
        _build_asset(item["step_id"], item["failure_behavior"], runner) for item in selected
    )


SHADOW_REGISTRY_ASSETS = build_shadow_registry_assets()


__all__ = [
    "ALLOWED_FAILURE_BEHAVIORS",
    "SHADOW_PILOT",
    "SHADOW_REGISTRY_ASSETS",
    "build_shadow_registry_assets",
    "compare_shadow_step",
    "load_registry_document",
    "select_shadow_pilot_steps",
    "shadow_step_payload",
]
