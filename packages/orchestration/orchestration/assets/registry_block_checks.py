"""Compile block_* registry steps into blocking Dagster checks.

Dagster skip is not the record. When a compiled check fails it first writes
registry-shaped ``blocked_upstream`` rows for DAG consumers, then returns a
blocking ``AssetCheckResult``. Those rows do not go into the daily
``steps.jsonl``; launchd remains the publication record.

Only non-core ``block_*`` steps with at least one compiled consumer may be
tagged ``execution.dagster_asset_check: blocking_pilot``. The graph lives
under ``registry_block`` and is not part of ``daily_job``.
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

from orchestration.assets.registry_quality_checks import read_quality_artifact
from orchestration.assets.registry_shadow import SHADOW_PILOT, load_registry_document
from orchestration.pipeline_dag import upstream_of

from verity.runtime.runtime_io import ROOT

BLOCKING_PILOT = "blocking_pilot"
ALLOWED_FAILURE_BEHAVIORS = frozenset(
    {
        "block_current_readout",
        "block_core_judgment",
        "block_promotion",
        "decision_adjacent_block",
    }
)
RecordFn = Callable[[Sequence[Mapping[str, Any]]], None]
ArtifactReader = Callable[[str], dict[str, Any]]
ConsumerHook = Callable[[str], None]


def block_source_passed(payload: Mapping[str, Any]) -> bool:
    return not payload.get("missing")


def make_blocked_upstream_records(
    failed_step_id: str,
    downstream_ids: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    """Return the same shape the daily sequence executor records on a block."""
    return tuple(
        {
            "step": down_id,
            "status": "blocked_upstream",
            "blocked_by": [failed_step_id],
            "duration_s": 0,
        }
        for down_id in downstream_ids
    )


def write_block_shadow_records(
    records: Sequence[Mapping[str, Any]],
    *,
    root: Path | None = None,
) -> Path | None:
    """Append shadow blocked_upstream rows. Never writes daily steps.jsonl."""
    if not records:
        return None
    path = (root or ROOT) / "Output" / "state" / "health" / "registry_block_shadow.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    return path


def downstream_of_step(step_id: str) -> tuple[str, ...]:
    """Active consumers whose compiled inputs are fed by ``step_id``.

    Consumers are always taken from the live registry DAG so a test document
    that only tags the blocking leaf still records the real blocked_upstream
    rows.
    """
    steps = load_registry_document().get("steps") or {}
    if not isinstance(steps, dict):
        return ()
    return tuple(
        str(consumer_id)
        for consumer_id, spec in steps.items()
        if isinstance(spec, dict)
        and spec.get("status") == "active"
        and consumer_id != step_id
        and step_id in upstream_of(str(consumer_id))
    )


def select_blocking_pilot_checks(document: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Return tagged block_* steps, or raise if a tag violates the batch-C gate."""
    steps = document.get("steps") or {}
    selected: list[dict[str, str]] = []
    errors: list[str] = []
    if not isinstance(steps, dict):
        raise ValueError("pipeline registry steps must be a mapping")
    for step_id, spec in steps.items():
        if not isinstance(spec, dict):
            continue
        execution = spec.get("execution") or {}
        if not isinstance(execution, dict) or execution.get("dagster_asset_check") != BLOCKING_PILOT:
            continue
        if execution.get("dagster_asset") == SHADOW_PILOT:
            errors.append(f"{step_id}: cannot be both dagster_asset and dagster_asset_check")
        authority = spec.get("authority") if isinstance(spec.get("authority"), dict) else {}
        failure_behavior = str(
            spec.get("failure_behavior") or authority.get("failure_behavior") or ""
        )
        affects_core = bool(
            spec.get("allowed_to_affect_core_judgment")
            or authority.get("affects_core_judgment")
        )
        status = str(spec.get("status") or "")
        artifact_path = str(spec.get("artifact_path") or "")
        if status != "active":
            errors.append(f"{step_id}: blocking_pilot requires status=active")
        if failure_behavior not in ALLOWED_FAILURE_BEHAVIORS:
            errors.append(
                f"{step_id}: blocking_pilot forbids failure_behavior={failure_behavior!r}"
            )
        if affects_core:
            errors.append(f"{step_id}: blocking_pilot forbids core-judgment steps")
        if execution.get("dagster_check_blocking") in {False, 0, "0", "false", "False"}:
            errors.append(f"{step_id}: blocking_pilot requires blocking checks")
        if not artifact_path:
            errors.append(f"{step_id}: blocking_pilot requires artifact_path")
        selected.append(
            {
                "step_id": str(step_id),
                "failure_behavior": failure_behavior,
                "artifact_path": artifact_path,
            }
        )
    if errors:
        raise ValueError("invalid registry blocking_pilot tags: " + "; ".join(errors))
    return tuple(selected)


def _build_source_asset(
    step_id: str,
    failure_behavior: str,
    artifact_path: str,
    read_artifact: ArtifactReader,
) -> AssetsDefinition:
    @asset(
        name=step_id,
        key_prefix=["registry_block"],
        compute_kind="registry_block",
        metadata={
            "step_id": step_id,
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
        },
    )
    def _registry_block_source() -> dict[str, Any]:
        payload = read_artifact(artifact_path)
        status = "success" if block_source_passed(payload) else "failed"
        return {
            "step": step_id,
            "status": status,
            "failure_behavior": failure_behavior,
            "authority": "shadow_only",
        }

    return _registry_block_source


def _build_blocking_check(
    step_id: str,
    failure_behavior: str,
    downstream_ids: tuple[str, ...],
    source: AssetsDefinition,
    record_fn: RecordFn,
) -> AssetChecksDefinition:
    @asset_check(
        asset=source,
        name=f"registry_block_{step_id}",
        blocking=True,
        compute_kind="registry_block",
    )
    def _registry_block_check(**kwargs: Any) -> AssetCheckResult:
        payload = next(iter(kwargs.values())) if kwargs else {}
        passed = payload.get("status") == "success"
        records = () if passed else make_blocked_upstream_records(step_id, downstream_ids)
        if records:
            record_fn(records)
        return AssetCheckResult(
            passed=passed,
            description="block_* failure records blocked_upstream before Dagster skip",
            metadata={
                "authority": "shadow_only",
                "check_blocking": True,
                "step_id": step_id,
                "failure_behavior": failure_behavior,
                "blocked_upstream_count": len(records),
            },
        )

    return _registry_block_check


def _build_consumer_asset(
    down_id: str,
    source_key: AssetKey,
    on_consumer: ConsumerHook,
) -> AssetsDefinition:
    @asset(
        name=down_id,
        key_prefix=["registry_block"],
        compute_kind="registry_block",
        ins={"upstream": AssetIn(key=source_key)},
        metadata={"step_id": down_id, "authority": "shadow_only"},
    )
    def _registry_block_consumer(upstream: dict[str, Any]) -> dict[str, Any]:
        on_consumer(down_id)
        return {
            "step": down_id,
            "status": "success",
            "authority": "shadow_only",
            "upstream_step": upstream.get("step"),
        }

    return _registry_block_consumer


def build_registry_block_defs(
    *,
    document: Mapping[str, Any] | None = None,
    root: Path | None = None,
    read_artifact: ArtifactReader | None = None,
    record_fn: RecordFn | None = None,
    on_consumer: ConsumerHook | None = None,
) -> tuple[tuple[AssetsDefinition, ...], tuple[AssetChecksDefinition, ...]]:
    workspace = root or ROOT
    registry = document or load_registry_document(workspace)
    selected = select_blocking_pilot_checks(registry)
    reader = read_artifact or (lambda path: read_quality_artifact(path, root=workspace))
    recorder = record_fn or (lambda rows: write_block_shadow_records(rows, root=workspace))
    mark = on_consumer or (lambda _down_id: None)
    assets: list[AssetsDefinition] = []
    checks: list[AssetChecksDefinition] = []
    for item in selected:
        step_id = item["step_id"]
        downstream_ids = downstream_of_step(step_id)
        if not downstream_ids:
            raise ValueError(
                f"{step_id}: blocking_pilot requires at least one DAG consumer "
                "so blocked_upstream can be recorded"
            )
        source = _build_source_asset(
            step_id, item["failure_behavior"], item["artifact_path"], reader
        )
        assets.append(source)
        checks.append(
            _build_blocking_check(
                step_id,
                item["failure_behavior"],
                downstream_ids,
                source,
                recorder,
            )
        )
        assets.extend(
            _build_consumer_asset(down_id, source.key, mark) for down_id in downstream_ids
        )
    return tuple(assets), tuple(checks)


BLOCK_REGISTRY_ASSETS, BLOCK_REGISTRY_CHECKS = build_registry_block_defs()


__all__ = [
    "ALLOWED_FAILURE_BEHAVIORS",
    "BLOCKING_PILOT",
    "BLOCK_REGISTRY_ASSETS",
    "BLOCK_REGISTRY_CHECKS",
    "block_source_passed",
    "build_registry_block_defs",
    "downstream_of_step",
    "make_blocked_upstream_records",
    "select_blocking_pilot_checks",
    "write_block_shadow_records",
]
