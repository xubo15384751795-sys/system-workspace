"""Stopped Dagster-native pilot for the first core writer boundaries.

This graph is intentionally separate from ``daily_job``.  Its asset checks
are blocking *inside the stopped pilot graph* so a failed core artifact cannot
look like a successful native migration, while ``authority=shadow_only`` and
``promotion_allowed=false`` keep the default pipeline unchanged.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml
from dagster import (
    AssetCheckResult,
    AssetChecksDefinition,
    AssetKey,
    AssetsDefinition,
    RetryPolicy,
    asset,
    asset_check,
)

from orchestration.native_core_boundaries import (
    execute_native_core_boundary,
    select_native_core_boundary_steps,
)
from scripts._runtime_io import ROOT

NATIVE_CORE_PILOT = "native_core_pilot"
NativeCoreBoundaryRunner = Callable[[str], dict[str, Any]]
_CORE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "quality_validation": ("neutral_pressure_measurement",),
}


def load_registry_document(root: Path | None = None) -> dict[str, Any]:
    """Load the registry used to decide which core steps enter the pilot."""
    path = (root or ROOT) / "governance" / "daily_pipeline_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("pipeline registry must be a mapping")
    return payload


def select_native_core_steps(document: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Expose the registry selection at the asset-graph boundary."""
    return select_native_core_boundary_steps(document)


def native_core_payload(
    result: Mapping[str, Any],
    *,
    step_id: str,
    failure_behavior: str,
) -> dict[str, Any]:
    """Normalize a core boundary result for Dagster and its blocking check."""
    return {
        "step": step_id,
        "status": str(result.get("status") or "error"),
        "artifact_status": str(result.get("artifact_status") or "UNKNOWN"),
        "check_passed": bool(result.get("check_passed")),
        "failure_behavior": failure_behavior,
        "authority": "shadow_only",
        "promotion_allowed": False,
        "writes_legacy_output": False,
        "writes_active_generation": bool(result.get("writes_active_generation")),
        "output_paths": list(result.get("output_paths") or []),
        "measurement_evidence": result.get("measurement_evidence"),
        "error": result.get("error"),
    }


def _default_boundary_runner(step_id: str) -> dict[str, Any]:
    """Run into a health-only shadow root when the stopped pilot is enabled."""
    result = execute_native_core_boundary(
        step_id,
        current_output=ROOT / "Output" / "health" / "native_core_shadow",
    )
    # The core adapter's explicit path is an active-generation boundary when
    # called by native_daily.  This stopped pilot intentionally points it at a
    # health-only root, so report that distinction honestly.
    return {**result, "writes_active_generation": False}


def _build_core_asset(
    item: Mapping[str, str],
    runner: NativeCoreBoundaryRunner,
    selected_ids: frozenset[str],
) -> AssetsDefinition:
    step_id = item["step_id"]
    failure_behavior = item["failure_behavior"]
    native_dependencies = tuple(
        dependency
        for dependency in _CORE_DEPENDENCIES.get(step_id, ())
        if dependency in selected_ids
    )

    @asset(
        name=step_id,
        key_prefix=[NATIVE_CORE_PILOT],
        deps=[
            AssetKey([NATIVE_CORE_PILOT, dependency])
            for dependency in native_dependencies
        ],
        compute_kind="dagster_native_core_boundary",
        retry_policy=RetryPolicy(max_retries=1, delay=5),
        metadata={
            "source_step": step_id,
            "migration_batch": "wave4-native-core-boundaries",
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
            "promotion_allowed": False,
            "writes_legacy_output": False,
            "upstream_steps": list(native_dependencies),
        },
    )
    def _native_core_asset() -> dict[str, Any]:
        result = runner(step_id)
        return native_core_payload(
            result,
            step_id=step_id,
            failure_behavior=failure_behavior,
        )

    return _native_core_asset


def build_native_core_assets(
    *,
    document: Mapping[str, Any] | None = None,
    boundary_runner: NativeCoreBoundaryRunner | None = None,
) -> tuple[AssetsDefinition, ...]:
    """Compile explicitly tagged core boundaries without the legacy runner."""
    registry = document if document is not None else load_registry_document()
    selected = select_native_core_steps(registry)
    runner = boundary_runner or _default_boundary_runner
    selected_ids = frozenset(item["step_id"] for item in selected)
    return tuple(_build_core_asset(item, runner, selected_ids) for item in selected)


def _build_core_check(asset_def: AssetsDefinition) -> AssetChecksDefinition:
    step_id = asset_def.key.path[-1]
    metadata = asset_def.metadata_by_key[asset_def.key]
    failure_behavior = str(metadata["failure_behavior"])

    @asset_check(
        asset=asset_def,
        name=f"native_core_{step_id}",
        blocking=True,
        compute_kind="dagster_native_core_check",
    )
    def _native_core_check(**kwargs: Any) -> AssetCheckResult:
        payload = next(iter(kwargs.values())) if kwargs else {}
        passed = (
            isinstance(payload, Mapping)
            and payload.get("step") == step_id
            and payload.get("status") == "success"
            and payload.get("check_passed") is True
            and payload.get("failure_behavior") == failure_behavior
            and payload.get("authority") == "shadow_only"
            and payload.get("promotion_allowed") is False
            and payload.get("writes_legacy_output") is False
        )
        return AssetCheckResult(
            passed=passed,
            description=(
                "core boundary artifact satisfies its declared check; "
                "failure blocks only this stopped shadow graph"
            ),
            metadata={
                "authority": "shadow_only",
                "check_blocking": True,
                "step_id": step_id,
                "failure_behavior": failure_behavior,
                "artifact_status": payload.get("artifact_status", "UNKNOWN")
                if isinstance(payload, Mapping)
                else "UNKNOWN",
            },
        )

    return _native_core_check


def build_native_core_checks(
    assets: tuple[AssetsDefinition, ...],
) -> tuple[AssetChecksDefinition, ...]:
    """Build blocking checks for the stopped core shadow graph."""
    return tuple(_build_core_check(asset_def) for asset_def in assets)


NATIVE_CORE_ASSETS = build_native_core_assets()
NATIVE_CORE_CHECKS = build_native_core_checks(NATIVE_CORE_ASSETS)


__all__ = [
    "NATIVE_CORE_ASSETS",
    "NATIVE_CORE_CHECKS",
    "NATIVE_CORE_PILOT",
    "build_native_core_assets",
    "build_native_core_checks",
    "load_registry_document",
    "native_core_payload",
    "select_native_core_steps",
]
