from __future__ import annotations

from pathlib import Path

import pytest
from dagster import (
    AssetCheckResult,
    asset,
    asset_check,
    materialize,
)

from orchestration.assets.data_quality import DATA_QUALITY_CHECKS
from orchestration.assets.registry_quality_checks import (
    REGISTRY_QUALITY_CHECKS,
    artifact_check_passed,
    build_registry_quality_checks,
    read_quality_artifact,
    select_shadow_pilot_checks,
)
from orchestration.definitions import daily_job, defs


def _check_names(checks) -> set[str]:
    return {spec.name for check in checks for spec in check.check_specs}


def test_live_registry_compiles_non_blocking_quality_checks() -> None:
    names = _check_names(REGISTRY_QUALITY_CHECKS)
    assert names == {
        "content_freshness_shadow",
        "registry_quality_measurement_quality_report",
    }
    assert all(not spec.blocking for check in REGISTRY_QUALITY_CHECKS for spec in check.check_specs)
    structural = next(
        spec
        for check in DATA_QUALITY_CHECKS
        for spec in check.check_specs
        if spec.name == "cross_asset_structural_contract"
    )
    assert structural.blocking is True


def test_daily_job_does_not_execute_quality_checks() -> None:
    node_names = {node.name for node in daily_job.nodes_in_topological_order}
    assert node_names == {"daily_job_entry"}
    defined = tuple(defs.asset_checks or ())
    for check in REGISTRY_QUALITY_CHECKS:
        assert check in defined


def test_shadow_quality_check_rejects_blocking_or_judgment_steps() -> None:
    document = {
        "steps": {
            "quality_validation": {
                "status": "active",
                "failure_behavior": "block_promotion",
                "allowed_to_affect_core_judgment": True,
                "artifact_path": "Output/current/quality_validation.json",
                "execution": {"mode": "subprocess", "dagster_asset_check": "shadow_pilot"},
            }
        }
    }
    with pytest.raises(ValueError, match="forbids failure_behavior='block_promotion'"):
        select_shadow_pilot_checks(document)

    document = {
        "steps": {
            "freshness_validator": {
                "status": "active",
                "failure_behavior": "block_core_judgment",
                "allowed_to_affect_core_judgment": True,
                "artifact_path": "Output/quality/freshness_report.json",
                "execution": {
                    "mode": "callable",
                    "dagster_asset_check": "shadow_pilot",
                    "dagster_check_blocking": True,
                },
            }
        }
    }
    with pytest.raises(ValueError, match="cannot be blocking"):
        select_shadow_pilot_checks(document)


def test_artifact_check_passed_is_fail_closed(tmp_path: Path) -> None:
    missing = read_quality_artifact("Output/current/measurement_quality.json", root=tmp_path)
    assert missing["missing"] is True
    assert artifact_check_passed(missing) is False
    assert artifact_check_passed({"overall_status": "OK"}) is True
    assert artifact_check_passed({"overall_status": "DEGRADED"}) is False
    assert artifact_check_passed({"status": "WARN"}) is True
    assert artifact_check_passed({}) is False


def test_failed_quality_check_does_not_block_downstream() -> None:
    materialized: list[str] = []

    @asset(name="fixture_release")
    def fixture_release() -> dict[str, object]:
        return {"status": "accepted", "release_id": "r1"}

    @asset(name="fixture_promoted")
    def fixture_promoted(fixture_release: dict[str, object]) -> dict[str, object]:
        materialized.append("fixture_promoted")
        return fixture_release

    @asset_check(asset=fixture_release, name="fixture_quality", blocking=False)
    def fixture_quality(fixture_release: dict[str, object]) -> AssetCheckResult:
        return AssetCheckResult(passed=False, metadata={"release_id": fixture_release["release_id"]})

    result = materialize([fixture_release, fixture_promoted, fixture_quality])

    assert result.success
    assert materialized == ["fixture_promoted"]


def test_compiled_artifact_check_reads_without_writing(tmp_path: Path) -> None:
    artifact = tmp_path / "Output/current/measurement_quality.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"overall_status": "OK"}\n', encoding="utf-8")
    before = artifact.read_bytes()
    reads: list[str] = []

    def fake_read(path: str) -> dict[str, object]:
        reads.append(path)
        return read_quality_artifact(path, root=tmp_path)

    checks = build_registry_quality_checks(
        document={
            "steps": {
                "measurement_quality_report": {
                    "status": "active",
                    "failure_behavior": "continue_with_warning",
                    "allowed_to_affect_core_judgment": False,
                    "artifact_path": "Output/current/measurement_quality.json",
                    "execution": {"mode": "callable", "dagster_asset_check": "shadow_pilot"},
                }
            }
        },
        root=tmp_path,
        read_artifact=fake_read,
        content_suite=lambda: {"success": True, "status": "PASS", "engine": "pandera", "critical_failures": []},
    )
    names = _check_names(checks)
    assert "registry_quality_measurement_quality_report" in names
    assert "content_freshness_shadow" in names
    assert all(not spec.blocking for check in checks for spec in check.check_specs)
    assert reads == []
    assert artifact.read_bytes() == before
    assert not list(tmp_path.glob("Output/quality/**"))
