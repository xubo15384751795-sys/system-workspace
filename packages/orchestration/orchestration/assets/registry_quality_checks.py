"""Compile registry quality evaluations into non-blocking Dagster asset checks.

These checks follow the DATA_QUALITY_CHECKS shape: they attach to
``harvester_release``, read already-produced evidence, and never run as part
of ``daily_job``. Every compiled check is ``blocking=False`` so a FAIL cannot
change launchd or promotion. Registry ``failure_behavior`` remains the
authority for those outcomes.

Only ``continue_with_warning`` steps that cannot affect core judgment may be
tagged ``execution.dagster_asset_check: shadow_pilot``. Content clocks come
from the registry ``content_freshness`` table; the suite check does not write
``Output/quality``.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from dagster import AssetCheckResult, AssetChecksDefinition, asset_check

from orchestration.assets.boundary_pilot import harvester_release
from orchestration.assets.registry_shadow import (
    ALLOWED_FAILURE_BEHAVIORS,
    SHADOW_PILOT,
    load_registry_document,
)

from verity.runtime.runtime_io import ROOT

ContentSuite = Callable[..., dict[str, Any]]
ArtifactReader = Callable[[str], dict[str, Any]]
_PASS_STATUSES = frozenset({"OK", "PASS", "WARN", "SUCCESS", "WATCH"})
_TRUTHY = frozenset({True, 1, "1", "true", "True", "yes", "YES"})


def _truthy(value: Any) -> bool:
    return value in _TRUTHY


def select_shadow_pilot_checks(document: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Return tagged quality steps, or raise if a tag violates the batch-B gate."""
    steps = document.get("steps") or {}
    selected: list[dict[str, str]] = []
    errors: list[str] = []
    if not isinstance(steps, dict):
        raise ValueError("pipeline registry steps must be a mapping")
    for step_id, spec in steps.items():
        if not isinstance(spec, dict):
            continue
        execution = spec.get("execution") or {}
        if not isinstance(execution, dict) or execution.get("dagster_asset_check") != SHADOW_PILOT:
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
            errors.append(f"{step_id}: shadow quality check requires status=active")
        if failure_behavior not in ALLOWED_FAILURE_BEHAVIORS:
            errors.append(
                f"{step_id}: shadow quality check forbids failure_behavior={failure_behavior!r}"
            )
        if affects_core:
            errors.append(f"{step_id}: shadow quality check forbids core-judgment steps")
        if _truthy(execution.get("dagster_check_blocking")):
            errors.append(f"{step_id}: shadow quality checks cannot be blocking")
        if not artifact_path:
            errors.append(f"{step_id}: shadow quality check requires artifact_path")
        selected.append(
            {
                "step_id": str(step_id),
                "failure_behavior": failure_behavior,
                "artifact_path": artifact_path,
            }
        )
    if errors:
        raise ValueError("invalid registry dagster_asset_check tags: " + "; ".join(errors))
    return tuple(selected)


def read_quality_artifact(relative_path: str, *, root: Path | None = None) -> dict[str, Any]:
    """Read a quality JSON artifact without creating or replacing it."""
    path = (root or ROOT) / relative_path
    if not path.exists():
        return {"missing": True, "path": relative_path, "status": "MISSING"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"missing": True, "path": relative_path, "status": "UNREADABLE"}
    if not isinstance(payload, dict):
        return {"missing": True, "path": relative_path, "status": "INVALID"}
    return payload


def artifact_check_passed(payload: Mapping[str, Any]) -> bool:
    """Map a quality artifact to a check result. Missing or unknown is fail-closed."""
    if payload.get("missing"):
        return False
    overall = str(payload.get("overall_status") or payload.get("status") or "").upper()
    if overall:
        return overall in _PASS_STATUSES
    if "success" in payload:
        return bool(payload.get("success"))
    return False


def content_suite_passed(payload: Mapping[str, Any]) -> bool:
    return bool(payload.get("success"))


def _check_result(*, passed: bool, description: str, metadata: Mapping[str, Any]) -> AssetCheckResult:
    return AssetCheckResult(
        passed=passed,
        description=description,
        metadata={
            "authority": "shadow_only",
            "check_blocking": False,
            **dict(metadata),
        },
    )


def _build_artifact_check(
    step_id: str,
    failure_behavior: str,
    artifact_path: str,
    read_artifact: ArtifactReader,
) -> AssetChecksDefinition:
    @asset_check(
        asset=harvester_release,
        name=f"registry_quality_{step_id}",
        blocking=False,
        compute_kind="registry_quality",
    )
    def _registry_quality_check(harvester_release: dict[str, Any]) -> AssetCheckResult:
        payload = read_artifact(artifact_path)
        return _check_result(
            passed=artifact_check_passed(payload),
            description="registry quality artifact is readable and not degraded",
            metadata={
                "step_id": step_id,
                "failure_behavior": failure_behavior,
                "artifact_path": artifact_path,
                "artifact_status": str(
                    payload.get("overall_status") or payload.get("status") or ""
                ),
                "release_id": str(harvester_release.get("release_id") or ""),
            },
        )

    return _registry_quality_check


def _build_content_freshness_check(suite_runner: ContentSuite) -> AssetChecksDefinition:
    @asset_check(
        asset=harvester_release,
        name="content_freshness_shadow",
        blocking=False,
        compute_kind="data_quality",
    )
    def content_freshness_shadow(harvester_release: dict[str, Any]) -> AssetCheckResult:
        payload = suite_runner()
        failures = payload.get("critical_failures") or []
        return _check_result(
            passed=content_suite_passed(payload),
            description="decision-critical content clocks are fresh (shadow, non-blocking)",
            metadata={
                "suite_status": str(payload.get("status") or ""),
                "engine": str(payload.get("engine") or ""),
                "critical_failure_count": len(failures) if isinstance(failures, list) else 0,
                "release_id": str(harvester_release.get("release_id") or ""),
            },
        )

    return content_freshness_shadow


def _default_content_suite(*, root: Path) -> dict[str, Any]:
    from orchestration.quality.content_freshness_suite import (
        run_content_freshness_quality_suite,
    )

    return run_content_freshness_quality_suite(root=root)


def build_registry_quality_checks(
    *,
    document: Mapping[str, Any] | None = None,
    root: Path | None = None,
    read_artifact: ArtifactReader | None = None,
    content_suite: ContentSuite | None = None,
) -> tuple[AssetChecksDefinition, ...]:
    workspace = root or ROOT
    selected = select_shadow_pilot_checks(document or load_registry_document(workspace))
    reader = read_artifact or (lambda path: read_quality_artifact(path, root=workspace))
    runner = content_suite or (lambda: _default_content_suite(root=workspace))
    tagged = tuple(
        _build_artifact_check(
            item["step_id"],
            item["failure_behavior"],
            item["artifact_path"],
            reader,
        )
        for item in selected
    )
    return (_build_content_freshness_check(runner), *tagged)


REGISTRY_QUALITY_CHECKS = build_registry_quality_checks()


__all__ = [
    "REGISTRY_QUALITY_CHECKS",
    "artifact_check_passed",
    "build_registry_quality_checks",
    "content_suite_passed",
    "read_quality_artifact",
    "select_shadow_pilot_checks",
]
