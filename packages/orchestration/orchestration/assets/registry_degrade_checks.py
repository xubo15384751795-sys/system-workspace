"""Compile hold_flat / claim-ceiling steps into a degrade-and-continue graph.

Dagster skip is forbidden here. Downstream shadow consumers still materialize
and are tagged ``degraded`` / ``degraded_by`` using the same shape the daily
sequence executor records. Checks are ``blocking=False`` so a failed hold_flat
source cannot vanish a trade or claim-ceiling card.

Only ``hold_flat`` and ``lower_claim_ceiling`` steps with at least one DAG
consumer may be tagged ``execution.dagster_asset_check: degrade_pilot``.
``research_only`` does not propagate and is refused. The graph lives under
``registry_degrade`` and is not part of ``daily_job``.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from dagster import (
    AssetCheckResult,
    AssetChecksDefinition,
    AssetIn,
    AssetKey,
    AssetsDefinition,
    asset,
    asset_check,
)

from orchestration.assets.registry_block_checks import (
    block_source_passed,
    downstream_of_step,
)
from orchestration.assets.registry_quality_checks import read_quality_artifact
from orchestration.assets.registry_shadow import SHADOW_PILOT, load_registry_document

from scripts._runtime_io import ROOT

DEGRADE_PILOT = "degrade_pilot"
ALLOWED_FAILURE_BEHAVIORS = frozenset({"hold_flat", "lower_claim_ceiling"})
_TRUTHY = frozenset({True, 1, "1", "true", "True", "yes", "YES"})
RecordFn = Callable[[Sequence[Mapping[str, Any]]], None]
ArtifactReader = Callable[[str], dict[str, Any]]
ConsumerHook = Callable[[str], None]


def make_degraded_records(
    failed_step_id: str,
    downstream_ids: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Return the same shape the daily sequence executor records on run_degraded."""
    return tuple(
        {
            "step": down_id,
            "status": "success",
            "degraded": True,
            "degraded_by": [failed_step_id],
            "duration_s": 0,
        }
        for down_id in downstream_ids
    )


def write_degrade_shadow_records(
    records: Sequence[Mapping[str, Any]],
    *,
    root: Path | None = None,
) -> Path | None:
    """Append shadow degraded rows. Never writes daily steps.jsonl."""
    if not records:
        return None
    path = (root or ROOT) / "Output" / "health" / "registry_degrade_shadow.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    return path


def select_degrade_pilot_checks(document: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Return tagged degrade steps, or raise if a tag violates the batch-D gate."""
    steps = document.get("steps") or {}
    selected: list[dict[str, str]] = []
    errors: list[str] = []
    if not isinstance(steps, dict):
        raise ValueError("pipeline registry steps must be a mapping")
    for step_id, spec in steps.items():
        if not isinstance(spec, dict):
            continue
        execution = spec.get("execution") or {}
        if not isinstance(execution, dict) or execution.get("dagster_asset_check") != DEGRADE_PILOT:
            continue
        if execution.get("dagster_asset") == SHADOW_PILOT:
            errors.append(f"{step_id}: cannot be both dagster_asset and dagster_asset_check")
        authority = spec.get("authority") if isinstance(spec.get("authority"), dict) else {}
        failure_behavior = str(
            spec.get("failure_behavior") or authority.get("failure_behavior") or ""
        )
        status = str(spec.get("status") or "")
        artifact_path = str(spec.get("artifact_path") or "")
        if status != "active":
            errors.append(f"{step_id}: degrade_pilot requires status=active")
        if failure_behavior == "research_only":
            errors.append(f"{step_id}: degrade_pilot forbids research_only (it does not propagate)")
        if failure_behavior not in ALLOWED_FAILURE_BEHAVIORS:
            errors.append(
                f"{step_id}: degrade_pilot forbids failure_behavior={failure_behavior!r}"
            )
        if execution.get("dagster_check_blocking") in _TRUTHY:
            errors.append(f"{step_id}: degrade_pilot forbids blocking checks")
        if not artifact_path:
            errors.append(f"{step_id}: degrade_pilot requires artifact_path")
        selected.append(
            {
                "step_id": str(step_id),
                "failure_behavior": failure_behavior,
                "artifact_path": artifact_path,
            }
        )
    if errors:
        raise ValueError("invalid registry degrade_pilot tags: " + "; ".join(errors))
    return tuple(selected)


def _build_source_asset(
    step_id: str,
    failure_behavior: str,
    artifact_path: str,
    read_artifact: ArtifactReader,
) -> AssetsDefinition:
    @asset(
        name=step_id,
        key_prefix=["registry_degrade"],
        compute_kind="registry_degrade",
        metadata={
            "step_id": step_id,
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
        },
    )
    def _registry_degrade_source() -> dict[str, Any]:
        payload = read_artifact(artifact_path)
        status = "success" if block_source_passed(payload) else "failed"
        return {
            "step": step_id,
            "status": status,
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
        }

    return _registry_degrade_source


def _build_degrade_check(
    step_id: str,
    failure_behavior: str,
    source: AssetsDefinition,
) -> AssetChecksDefinition:
    @asset_check(
        asset=source,
        name=f"registry_degrade_{step_id}",
        blocking=False,
        compute_kind="registry_degrade",
    )
    def _registry_degrade_check(**kwargs: Any) -> AssetCheckResult:
        payload = next(iter(kwargs.values())) if kwargs else {}
        passed = payload.get("status") == "success"
        return AssetCheckResult(
            passed=passed,
            description="hold_flat/claim-ceiling failure degrades consumers; it must not skip them",
            metadata={
                "authority": "shadow_only",
                "check_blocking": False,
                "step_id": step_id,
                "failure_behavior": failure_behavior,
            },
        )

    return _registry_degrade_check


def _build_consumer_asset(
    down_id: str,
    source_key: AssetKey,
    failed_step_id: str,
    record_fn: RecordFn,
    on_consumer: ConsumerHook,
) -> AssetsDefinition:
    @asset(
        name=down_id,
        key_prefix=["registry_degrade"],
        compute_kind="registry_degrade",
        ins={"upstream": AssetIn(key=source_key)},
        metadata={"step_id": down_id, "authority": "shadow_only"},
    )
    def _registry_degrade_consumer(upstream: dict[str, Any]) -> dict[str, Any]:
        on_consumer(down_id)
        result: dict[str, Any] = {
            "step": down_id,
            "status": "success",
            "authority": "shadow_only",
            "upstream_step": upstream.get("step"),
            "duration_s": 0,
        }
        if upstream.get("status") != "success":
            result["degraded"] = True
            result["degraded_by"] = [failed_step_id]
            record_fn(
                make_degraded_records(failed_step_id, (down_id,))
            )
        return result

    return _registry_degrade_consumer


def build_registry_degrade_defs(
    *,
    document: Mapping[str, Any] | None = None,
    root: Path | None = None,
    read_artifact: ArtifactReader | None = None,
    record_fn: RecordFn | None = None,
    on_consumer: ConsumerHook | None = None,
) -> tuple[tuple[AssetsDefinition, ...], tuple[AssetChecksDefinition, ...]]:
    workspace = root or ROOT
    registry = document or load_registry_document(workspace)
    selected = select_degrade_pilot_checks(registry)
    reader = read_artifact or (lambda path: read_quality_artifact(path, root=workspace))
    recorder = record_fn or (lambda rows: write_degrade_shadow_records(rows, root=workspace))
    mark = on_consumer or (lambda _down_id: None)
    assets: list[AssetsDefinition] = []
    checks: list[AssetChecksDefinition] = []
    for item in selected:
        step_id = item["step_id"]
        downstream_ids = downstream_of_step(step_id)
        if not downstream_ids:
            raise ValueError(
                f"{step_id}: degrade_pilot requires at least one DAG consumer "
                "so degraded_by can be recorded"
            )
        source = _build_source_asset(
            step_id, item["failure_behavior"], item["artifact_path"], reader
        )
        assets.append(source)
        checks.append(_build_degrade_check(step_id, item["failure_behavior"], source))
        assets.extend(
            _build_consumer_asset(down_id, source.key, step_id, recorder, mark)
            for down_id in downstream_ids
        )
    return tuple(assets), tuple(checks)


DEGRADE_REGISTRY_ASSETS, DEGRADE_REGISTRY_CHECKS = build_registry_degrade_defs()


__all__ = [
    "ALLOWED_FAILURE_BEHAVIORS",
    "DEGRADE_PILOT",
    "DEGRADE_REGISTRY_ASSETS",
    "DEGRADE_REGISTRY_CHECKS",
    "build_registry_degrade_defs",
    "make_degraded_records",
    "select_degrade_pilot_checks",
    "write_degrade_shadow_records",
]
