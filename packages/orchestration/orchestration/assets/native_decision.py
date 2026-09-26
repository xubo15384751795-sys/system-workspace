"""Stopped Dagster-native pilot for the judgment-to-risk decision chain."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from dagster import (
    AssetCheckResult,
    AssetChecksDefinition,
    AssetKey,
    AssetsDefinition,
    RetryPolicy,
    asset,
    asset_check,
)

from orchestration.native_decision_boundaries import (
    execute_native_decision_boundary,
    select_native_decision_boundary_steps,
)
from verity.runtime.runtime_io import ROOT

NATIVE_DECISION_PILOT = "native_decision_pilot"
NativeDecisionBoundaryRunner = Callable[[str], dict[str, Any]]
_DECISION_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "judgment_promotion_gate": ("judgment_layer",),
    "trade_decision": ("judgment_layer", "judgment_promotion_gate"),
    "risk_gate": ("trade_decision",),
}


def load_registry_document(root=ROOT) -> dict[str, Any]:
    from orchestration.native_decision_boundaries import _load_registry

    return _load_registry(root)


def select_native_decision_steps(
    document: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    return select_native_decision_boundary_steps(document)


def native_decision_payload(
    result: Mapping[str, Any],
    *,
    step_id: str,
    failure_behavior: str,
) -> dict[str, Any]:
    payload = result.get("payload")
    policy_status = None
    if isinstance(payload, Mapping):
        policy_status = payload.get("overall_status") or payload.get("status")
        if step_id == "risk_gate":
            risk_check = payload.get("risk_check")
            if isinstance(risk_check, Mapping):
                policy_status = risk_check.get("status")
        elif step_id in {"judgment_layer", "trade_decision"}:
            policy_status = payload.get("decision") or payload.get("stance") or policy_status
    return {
        "step": step_id,
        "status": str(result.get("status") or "error"),
        "artifact_status": str(result.get("artifact_status") or "UNKNOWN"),
        "check_passed": bool(result.get("check_passed")),
        "policy_status": str(policy_status or "UNKNOWN"),
        "failure_behavior": failure_behavior,
        "authority": "shadow_only",
        "promotion_allowed": False,
        "writes_legacy_output": False,
        "writes_active_generation": False,
        "writes_shadow_output": bool(result.get("writes_shadow_output")),
        "output_paths": list(result.get("output_paths") or []),
        "error": result.get("error"),
    }


def _default_boundary_runner(step_id: str) -> dict[str, Any]:
    return execute_native_decision_boundary(step_id)


def _build_decision_asset(
    item: Mapping[str, str],
    runner: NativeDecisionBoundaryRunner,
    selected_ids: frozenset[str],
) -> AssetsDefinition:
    step_id = item["step_id"]
    failure_behavior = item["failure_behavior"]
    dependencies = tuple(
        dependency
        for dependency in _DECISION_DEPENDENCIES.get(step_id, ())
        if dependency in selected_ids
    )

    @asset(
        name=step_id,
        key_prefix=[NATIVE_DECISION_PILOT],
        deps=[
            AssetKey([NATIVE_DECISION_PILOT, dependency]) for dependency in dependencies
        ],
        compute_kind="dagster_native_decision_boundary",
        retry_policy=RetryPolicy(max_retries=1, delay=5),
        metadata={
            "source_step": step_id,
            "migration_batch": "wave4-native-decision-boundaries",
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
            "promotion_allowed": False,
            "writes_legacy_output": False,
            "writes_active_generation": False,
            "upstream_steps": list(dependencies),
        },
    )
    def _native_decision_asset() -> dict[str, Any]:
        result = runner(step_id)
        return native_decision_payload(
            result,
            step_id=step_id,
            failure_behavior=failure_behavior,
        )

    return _native_decision_asset


def build_native_decision_assets(
    *,
    document: Mapping[str, Any] | None = None,
    boundary_runner: NativeDecisionBoundaryRunner | None = None,
) -> tuple[AssetsDefinition, ...]:
    registry = document if document is not None else load_registry_document()
    selected = select_native_decision_steps(registry)
    runner = boundary_runner or _default_boundary_runner
    selected_ids = frozenset(item["step_id"] for item in selected)
    return tuple(_build_decision_asset(item, runner, selected_ids) for item in selected)


def _build_decision_check(asset_def: AssetsDefinition) -> AssetChecksDefinition:
    step_id = asset_def.key.path[-1]
    metadata = asset_def.metadata_by_key[asset_def.key]
    failure_behavior = str(metadata["failure_behavior"])

    @asset_check(
        asset=asset_def,
        name=f"native_decision_artifact_{step_id}",
        blocking=True,
        compute_kind="dagster_native_decision_check",
    )
    def _native_decision_check(**kwargs: Any) -> AssetCheckResult:
        payload = next(iter(kwargs.values())) if kwargs else {}
        passed = (
            isinstance(payload, Mapping)
            and payload.get("step") == step_id
            and payload.get("status") == "success"
            and payload.get("artifact_status") == "PASS"
            and payload.get("check_passed") is True
            and payload.get("failure_behavior") == failure_behavior
            and payload.get("authority") == "shadow_only"
            and payload.get("promotion_allowed") is False
            and payload.get("writes_legacy_output") is False
            and payload.get("writes_active_generation") is False
            and payload.get("writes_shadow_output") is True
        )
        return AssetCheckResult(
            passed=passed,
            description=(
                "decision boundary artifact is valid; policy BLOCKED/WATCH "
                "statuses remain data, while execution errors block downstream assets"
            ),
            metadata={
                "authority": "shadow_only",
                "check_blocking": True,
                "step_id": step_id,
                "failure_behavior": failure_behavior,
                "policy_status": payload.get("policy_status", "UNKNOWN")
                if isinstance(payload, Mapping)
                else "UNKNOWN",
            },
        )

    return _native_decision_check


def build_native_decision_checks(
    assets: tuple[AssetsDefinition, ...],
) -> tuple[AssetChecksDefinition, ...]:
    return tuple(_build_decision_check(asset_def) for asset_def in assets)


NATIVE_DECISION_ASSETS = build_native_decision_assets()
NATIVE_DECISION_CHECKS = build_native_decision_checks(NATIVE_DECISION_ASSETS)


__all__ = [
    "NATIVE_DECISION_ASSETS",
    "NATIVE_DECISION_CHECKS",
    "NATIVE_DECISION_PILOT",
    "build_native_decision_assets",
    "build_native_decision_checks",
    "load_registry_document",
    "native_decision_payload",
    "select_native_decision_steps",
]
