"""Compile one registry quality-report pilot into a native asset and check."""
from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from dagster import AssetCheckResult, AssetChecksDefinition, AssetsDefinition, RetryPolicy, asset, asset_check

from verity.runtime.runtime_io import ROOT

NATIVE_QUALITY_PILOT = "native_quality_pilot"
ALLOWED_FAILURE_BEHAVIORS = frozenset({"continue_with_warning"})
_PASS_STATUSES = frozenset({"OK", "PASS", "WARN", "SUCCESS", "WATCH"})
NativeQualityCallable = Callable[[], dict[str, Any]]


def load_registry_document(root: Path | None = None) -> dict[str, Any]:
    path = (root or ROOT) / "governance" / "daily_pipeline_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("pipeline registry must be a mapping")
    return payload


def select_native_quality_steps(document: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Select only active, non-core, non-blocking quality-report pilots."""
    steps = document.get("steps") or {}
    if not isinstance(steps, Mapping):
        raise ValueError("pipeline registry steps must be a mapping")

    selected: list[dict[str, str]] = []
    errors: list[str] = []
    for step_id, spec in steps.items():
        if not isinstance(spec, Mapping):
            continue
        execution = spec.get("execution") or {}
        if not isinstance(execution, Mapping) or execution.get("dagster_native_asset") != NATIVE_QUALITY_PILOT:
            continue
        authority = spec.get("authority") if isinstance(spec.get("authority"), Mapping) else {}
        failure_behavior = str(
            spec.get("failure_behavior") or authority.get("failure_behavior") or ""
        )
        affects_core = bool(
            spec.get("allowed_to_affect_core_judgment")
            or authority.get("affects_core_judgment")
        )
        status = str(spec.get("status") or "")
        native_callable = execution.get("native_callable")
        if status != "active":
            errors.append(f"{step_id}: native_quality_pilot requires status=active")
        if failure_behavior not in ALLOWED_FAILURE_BEHAVIORS:
            errors.append(
                f"{step_id}: native_quality_pilot forbids failure_behavior={failure_behavior!r}"
            )
        if affects_core:
            errors.append(f"{step_id}: native_quality_pilot forbids core-judgment steps")
        if (
            not isinstance(native_callable, str)
            or native_callable.count(":") != 1
            or any(not part.strip() for part in native_callable.split(":", 1))
        ):
            errors.append(f"{step_id}: native_quality_pilot requires execution.native_callable")
        selected.append(
            {
                "step_id": str(step_id),
                "failure_behavior": failure_behavior,
                "native_callable": str(native_callable or ""),
            }
        )
    if errors:
        raise ValueError("invalid registry native_quality_pilot tags: " + "; ".join(errors))
    return tuple(selected)


def _eager_callable_resolution_allowed() -> bool:
    from system_runtime.paths import generation_mode_enabled

    if not generation_mode_enabled():
        return True
    return bool(os.environ.get("SYSTEM_GENERATION_DIR", "").strip())


def _resolve_native_quality_callable(reference: str) -> NativeQualityCallable:
    module_name, function_name = reference.rsplit(":", 1)
    module = importlib.import_module(module_name)
    candidate = getattr(module, function_name, None)
    if not callable(candidate):
        raise TypeError(f"native quality callable is not callable: {reference}")
    return cast(NativeQualityCallable, candidate)


def native_quality_payload(
    report: dict[str, Any],
    *,
    step_id: str,
    failure_behavior: str,
) -> dict[str, Any]:
    return {
        "step": step_id,
        "status": str(report.get("overall_status") or "UNKNOWN").upper(),
        "failure_behavior": failure_behavior,
        "authority": "shadow_only",
        "writes_legacy_output": False,
        "report": report,
    }


def _build_quality_asset(item: Mapping[str, str]) -> AssetsDefinition:
    step_id = item["step_id"]
    failure_behavior = item["failure_behavior"]
    native_callable = item["native_callable"]

    @asset(
        name=step_id,
        key_prefix=["native_quality"],
        compute_kind="dagster_native_quality_asset",
        retry_policy=RetryPolicy(max_retries=1, delay=5),
        metadata={
            "source_step": step_id,
            "migration_batch": "wave4-native-quality-pilot",
            "native_callable": native_callable,
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
            "writes_legacy_output": False,
        },
    )
    def _native_quality_asset() -> dict[str, Any]:
        report = _resolve_native_quality_callable(native_callable)()
        return native_quality_payload(
            report,
            step_id=step_id,
            failure_behavior=failure_behavior,
        )

    return _native_quality_asset


def build_native_quality_assets(
    *,
    document: Mapping[str, Any] | None = None,
) -> tuple[AssetsDefinition, ...]:
    registry = document if document is not None else load_registry_document()
    selected = select_native_quality_steps(registry)
    if _eager_callable_resolution_allowed():
        for item in selected:
            try:
                _resolve_native_quality_callable(item["native_callable"])
            except (ImportError, AttributeError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"{item['step_id']}: native quality callable cannot be resolved: "
                    f"{item['native_callable']}"
                ) from exc
    return tuple(_build_quality_asset(item) for item in selected)


def _build_quality_check(asset_def: AssetsDefinition) -> AssetChecksDefinition:
    step_id = asset_def.key.path[-1]
    metadata = asset_def.metadata_by_key[asset_def.key]
    failure_behavior = str(metadata["failure_behavior"])

    @asset_check(
        asset=asset_def,
        name=f"native_quality_{step_id}",
        blocking=False,
        compute_kind="dagster_native_quality_check",
    )
    def _native_quality_check(**kwargs: Any) -> AssetCheckResult:
        payload = next(iter(kwargs.values())) if kwargs else {}
        report = payload.get("report") if isinstance(payload, Mapping) else {}
        status = str(report.get("overall_status") or "").upper() if isinstance(report, Mapping) else ""
        return AssetCheckResult(
            passed=status in _PASS_STATUSES,
            description="native quality report is present and not degraded",
            metadata={
                "authority": "shadow_only",
                "check_blocking": False,
                "step_id": step_id,
                "failure_behavior": failure_behavior,
                "overall_status": status or "UNKNOWN",
            },
        )

    return _native_quality_check


def build_native_quality_checks(
    assets: tuple[AssetsDefinition, ...],
) -> tuple[AssetChecksDefinition, ...]:
    return tuple(_build_quality_check(asset_def) for asset_def in assets)


NATIVE_QUALITY_ASSETS = build_native_quality_assets()
NATIVE_QUALITY_CHECKS = build_native_quality_checks(NATIVE_QUALITY_ASSETS)


__all__ = [
    "ALLOWED_FAILURE_BEHAVIORS",
    "NATIVE_QUALITY_ASSETS",
    "NATIVE_QUALITY_CHECKS",
    "NATIVE_QUALITY_PILOT",
    "build_native_quality_assets",
    "build_native_quality_checks",
    "load_registry_document",
    "native_quality_payload",
    "select_native_quality_steps",
]
