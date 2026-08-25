"""Compile registry-tagged steps into a first Dagster-native asset batch.

The registry remains the authority for eligibility and failure semantics.  A
step is compiled here only when it is explicitly tagged with
``execution.dagster_native_asset: native_pilot`` and provides a direct
``module:function`` callable.  The callable is invoked without the legacy
``pipeline_runner`` or ``steps.jsonl`` writer, while the asset remains
``shadow_only`` until a recorded parity window authorizes promotion.
"""
from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

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

from scripts._runtime_io import ROOT

NATIVE_BATCH = "native_batch"
NATIVE_PILOT = "native_pilot"
ALLOWED_FAILURE_BEHAVIORS = frozenset({"continue_with_warning"})
_BUILD_DATA_GAPS_REF = "scripts.commands.weekly.build_data_gaps:build_data_gaps"
NativeCallable = Callable[[], dict[str, Any]]


def build_data_gaps() -> dict[str, Any]:
    """Lazy wrapper so Definitions can load before a generation directory exists."""
    from scripts.commands.weekly.build_data_gaps import build_data_gaps as _impl

    return _impl()


def load_registry_document(root: Path | None = None) -> dict[str, Any]:
    """Load the registry used to decide which steps enter this native batch."""
    path = (root or ROOT) / "governance" / "daily_pipeline_registry.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("pipeline registry must be a mapping")
    return payload


def select_native_pilot_steps(document: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Validate and return the explicitly tagged native-pilot steps.

    The first migration batch is intentionally restricted to non-core,
    ``continue_with_warning`` leaves.  Blocking and judgment-adjacent steps
    must wait for native asset checks and a separately approved cutover.
    """
    steps = document.get("steps") or {}
    if not isinstance(steps, Mapping):
        raise ValueError("pipeline registry steps must be a mapping")

    selected: list[dict[str, Any]] = []
    errors: list[str] = []
    for step_id, spec in steps.items():
        if not isinstance(spec, Mapping):
            continue
        execution = spec.get("execution") or {}
        if not isinstance(execution, Mapping) or execution.get("dagster_native_asset") != NATIVE_PILOT:
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
        native_depends_on = execution.get("native_depends_on") or ()
        if isinstance(native_depends_on, str):
            native_depends_on = (native_depends_on,)
        elif isinstance(native_depends_on, (list, tuple)):
            native_depends_on = tuple(str(item) for item in native_depends_on)
        else:
            errors.append(f"{step_id}: native_depends_on must be a list of step ids")
            native_depends_on = ()
        if len(set(native_depends_on)) != len(native_depends_on):
            errors.append(f"{step_id}: native_depends_on contains duplicates")
        if str(step_id) in native_depends_on:
            errors.append(f"{step_id}: native_depends_on cannot contain itself")

        if status != "active":
            errors.append(f"{step_id}: native_pilot requires status=active")
        if failure_behavior not in ALLOWED_FAILURE_BEHAVIORS:
            errors.append(
                f"{step_id}: native_pilot forbids failure_behavior={failure_behavior!r}"
            )
        if affects_core:
            errors.append(f"{step_id}: native_pilot forbids core-judgment steps")
        if (
            not isinstance(native_callable, str)
            or native_callable.count(":") != 1
            or any(not part.strip() for part in native_callable.split(":", 1))
        ):
            errors.append(f"{step_id}: native_pilot requires execution.native_callable")

        item: dict[str, Any] = {
            "step_id": str(step_id),
            "failure_behavior": failure_behavior,
            "native_callable": str(native_callable or ""),
        }
        if native_depends_on:
            item["native_depends_on"] = native_depends_on
        selected.append(item)

    if errors:
        raise ValueError("invalid registry native_pilot tags: " + "; ".join(errors))
    return tuple(selected)


def _eager_callable_resolution_allowed() -> bool:
    """Writer modules may touch current surfaces at import.

    launchd sets SYSTEM_GENERATION_MODE before a generation directory exists,
    so Definitions load must not import those modules yet.
    """
    from system_runtime.paths import generation_mode_enabled

    if not generation_mode_enabled():
        return True
    return bool(os.environ.get("SYSTEM_GENERATION_DIR", "").strip())


def _resolve_native_callable(reference: str) -> NativeCallable:
    """Resolve a registry ``module:function`` without routing through the runner."""
    if reference == _BUILD_DATA_GAPS_REF:
        # Keep this lookup late so focused tests and controlled operator runs
        # can replace the pure callable without rebuilding Definitions.
        return build_data_gaps

    module_name, function_name = reference.rsplit(":", 1)
    module = importlib.import_module(module_name)
    candidate = getattr(module, function_name, None)
    if not callable(candidate):
        raise TypeError(f"native callable is not callable: {reference}")
    return cast(NativeCallable, candidate)


def native_batch_payload(
    report: dict[str, Any],
    *,
    step_id: str = "build_data_gaps",
    failure_behavior: str = "continue_with_warning",
) -> dict[str, Any]:
    """Wrap a native report with explicit shadow authority and semantics."""
    return {
        "step": step_id,
        "status": "degraded" if report.get("error") else "success",
        "failure_behavior": failure_behavior,
        "authority": "shadow_only",
        "writes_legacy_output": False,
        "report": report,
    }


def _build_native_asset(item: Mapping[str, str]) -> AssetsDefinition:
    step_id = item["step_id"]
    failure_behavior = item["failure_behavior"]
    native_callable = item["native_callable"]
    native_depends_on = tuple(str(dep) for dep in item.get("native_depends_on", ()))

    @asset(
        name=step_id,
        key_prefix=[NATIVE_BATCH],
        compute_kind="dagster_native_asset",
        retry_policy=RetryPolicy(max_retries=1, delay=5),
        deps=[AssetKey([NATIVE_BATCH, dependency]) for dependency in native_depends_on],
        metadata={
            "source_step": step_id,
            "migration_batch": "wave4-native-registry-pilot",
            "native_callable": native_callable,
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
            "writes_legacy_output": False,
            "native_depends_on": list(native_depends_on),
        },
    )
    def _native_step() -> dict[str, Any]:
        report = _resolve_native_callable(native_callable)()
        return native_batch_payload(
            report,
            step_id=step_id,
            failure_behavior=failure_behavior,
        )

    return _native_step


def build_native_batch_assets(
    *,
    document: Mapping[str, Any] | None = None,
) -> tuple[AssetsDefinition, ...]:
    """Build native assets from the registry's explicit native-pilot tags."""
    registry = document if document is not None else load_registry_document()
    selected = select_native_pilot_steps(registry)
    selected_ids = {item["step_id"] for item in selected}
    dependency_errors = [
        f"{item['step_id']}: native_depends_on references non-native step {dependency!r}"
        for item in selected
        for dependency in item.get("native_depends_on", ())
        if dependency not in selected_ids
    ]
    if dependency_errors:
        raise ValueError("invalid native_pilot dependencies: " + "; ".join(dependency_errors))
    if _eager_callable_resolution_allowed():
        for item in selected:
            try:
                _resolve_native_callable(item["native_callable"])
            except (ImportError, AttributeError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"{item['step_id']}: native_pilot callable cannot be resolved: "
                    f"{item['native_callable']}"
                ) from exc
    return tuple(_build_native_asset(item) for item in selected)


def _build_native_contract_check(asset_def: AssetsDefinition) -> AssetChecksDefinition:
    step_id = asset_def.key.path[-1]
    metadata = asset_def.metadata_by_key[asset_def.key]
    failure_behavior = str(metadata["failure_behavior"])

    @asset_check(
        asset=asset_def,
        name=f"native_contract_{step_id}",
        blocking=False,
        compute_kind="dagster_native_asset_check",
    )
    def _native_contract_check(**kwargs: Any) -> AssetCheckResult:
        payload = next(iter(kwargs.values())) if kwargs else {}
        passed = (
            isinstance(payload, Mapping)
            and payload.get("step") == step_id
            and payload.get("failure_behavior") == failure_behavior
            and payload.get("authority") == "shadow_only"
            and payload.get("writes_legacy_output") is False
            and isinstance(payload.get("report"), Mapping)
        )
        return AssetCheckResult(
            passed=passed,
            description="native pilot payload preserves the shadow and legacy-write boundaries",
            metadata={
                "authority": "shadow_only",
                "check_blocking": False,
                "step_id": step_id,
                "failure_behavior": failure_behavior,
            },
        )

    return _native_contract_check


def build_native_batch_checks(
    assets: tuple[AssetsDefinition, ...],
) -> tuple[AssetChecksDefinition, ...]:
    """Build non-blocking contract checks for a native-pilot asset batch."""
    return tuple(_build_native_contract_check(asset_def) for asset_def in assets)


NATIVE_BATCH_ASSETS = build_native_batch_assets()
NATIVE_BATCH_CHECKS = build_native_batch_checks(NATIVE_BATCH_ASSETS)

# Compatibility export for callers that named the first pilot asset directly.
build_data_gaps_native: AssetsDefinition = next(
    asset_def
    for asset_def in NATIVE_BATCH_ASSETS
    if asset_def.key.path == [NATIVE_BATCH, "build_data_gaps"]
)


__all__ = [
    "ALLOWED_FAILURE_BEHAVIORS",
    "NATIVE_BATCH",
    "NATIVE_BATCH_ASSETS",
    "NATIVE_BATCH_CHECKS",
    "NATIVE_PILOT",
    "build_data_gaps_native",
    "build_native_batch_assets",
    "build_native_batch_checks",
    "load_registry_document",
    "native_batch_payload",
    "select_native_pilot_steps",
]
