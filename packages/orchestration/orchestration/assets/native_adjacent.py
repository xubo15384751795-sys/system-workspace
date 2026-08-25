"""Stopped Dagster pilot for ledger and paper-position side effects."""

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

from orchestration.native_adjacent_boundaries import (
    execute_native_adjacent_boundary,
    select_native_adjacent_boundary_steps,
)
from scripts._runtime_io import ROOT

NATIVE_ADJACENT_PILOT = "native_adjacent_pilot"
NativeAdjacentBoundaryRunner = Callable[[str], dict[str, Any]]
_ADJACENT_DEPENDENCIES: dict[str, tuple[AssetKey, ...]] = {
    "record_trade_decision": (
        AssetKey(["native_decision_pilot", "trade_decision"]),
        AssetKey(["native_decision_pilot", "risk_gate"]),
    ),
    "paper_portfolio": (
        AssetKey(["native_decision_pilot", "trade_decision"]),
        AssetKey(["native_core_pilot", "neutral_pressure_measurement"]),
    ),
}


def load_registry_document(root=ROOT) -> dict[str, Any]:
    from orchestration.native_adjacent_boundaries import _load_registry

    return _load_registry(root)


def select_native_adjacent_steps(
    document: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    return select_native_adjacent_boundary_steps(document)


def native_adjacent_payload(
    result: Mapping[str, Any],
    *,
    step_id: str,
    failure_behavior: str,
) -> dict[str, Any]:
    payload = result.get("payload")
    policy_status = None
    if isinstance(payload, Mapping):
        policy_status = (
            payload.get("risk_gate_status")
            or payload.get("stance")
            or payload.get("as_of_date")
        )
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
        "input_path_rebases": list(result.get("input_path_rebases") or []),
        "claim_evaluation_status": (
            payload.get("claim_evaluation_status")
            if isinstance(payload, Mapping)
            else None
        ),
        "claim_evaluation_error": (
            payload.get("claim_evaluation_error")
            if isinstance(payload, Mapping)
            else None
        ),
        "error": result.get("error"),
    }


def _default_boundary_runner(step_id: str) -> dict[str, Any]:
    return execute_native_adjacent_boundary(step_id)


def _build_adjacent_asset(
    item: Mapping[str, str],
    runner: NativeAdjacentBoundaryRunner,
) -> AssetsDefinition:
    step_id = item["step_id"]
    failure_behavior = item["failure_behavior"]

    @asset(
        name=step_id,
        key_prefix=[NATIVE_ADJACENT_PILOT],
        deps=list(_ADJACENT_DEPENDENCIES.get(step_id, ())),
        compute_kind="dagster_native_adjacent_boundary",
        retry_policy=RetryPolicy(max_retries=1, delay=5),
        metadata={
            "source_step": step_id,
            "migration_batch": "wave4-native-adjacent-boundaries",
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
            "promotion_allowed": False,
            "writes_legacy_output": False,
            "writes_active_generation": False,
            "upstream_steps": [
                asset_key.to_user_string()
                for asset_key in _ADJACENT_DEPENDENCIES.get(step_id, ())
            ],
        },
    )
    def _native_adjacent_asset() -> dict[str, Any]:
        result = runner(step_id)
        return native_adjacent_payload(
            result,
            step_id=step_id,
            failure_behavior=failure_behavior,
        )

    return _native_adjacent_asset


def build_native_adjacent_assets(
    *,
    document: Mapping[str, Any] | None = None,
    boundary_runner: NativeAdjacentBoundaryRunner | None = None,
) -> tuple[AssetsDefinition, ...]:
    registry = document if document is not None else load_registry_document()
    selected = select_native_adjacent_steps(registry)
    runner = boundary_runner or _default_boundary_runner
    return tuple(_build_adjacent_asset(item, runner) for item in selected)


def _build_adjacent_check(asset_def: AssetsDefinition) -> AssetChecksDefinition:
    step_id = asset_def.key.path[-1]
    metadata = asset_def.metadata_by_key[asset_def.key]
    failure_behavior = str(metadata["failure_behavior"])
    blocking = failure_behavior == "decision_adjacent_block"

    @asset_check(
        asset=asset_def,
        name=f"native_adjacent_artifact_{step_id}",
        blocking=blocking,
        compute_kind="dagster_native_adjacent_check",
    )
    def _native_adjacent_check(**kwargs: Any) -> AssetCheckResult:
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
                "adjacent writer artifact is valid; record warnings remain non-blocking, "
                "while paper-position failures block downstream descendants"
            ),
            metadata={
                "authority": "shadow_only",
                "check_blocking": blocking,
                "step_id": step_id,
                "failure_behavior": failure_behavior,
                "policy_status": payload.get("policy_status", "UNKNOWN")
                if isinstance(payload, Mapping)
                else "UNKNOWN",
            },
        )

    return _native_adjacent_check


def build_native_adjacent_checks(
    assets: tuple[AssetsDefinition, ...],
) -> tuple[AssetChecksDefinition, ...]:
    return tuple(_build_adjacent_check(asset_def) for asset_def in assets)


NATIVE_ADJACENT_ASSETS = build_native_adjacent_assets()
NATIVE_ADJACENT_CHECKS = build_native_adjacent_checks(NATIVE_ADJACENT_ASSETS)


__all__ = [
    "NATIVE_ADJACENT_ASSETS",
    "NATIVE_ADJACENT_CHECKS",
    "NATIVE_ADJACENT_PILOT",
    "build_native_adjacent_assets",
    "build_native_adjacent_checks",
    "load_registry_document",
    "native_adjacent_payload",
    "select_native_adjacent_steps",
]
