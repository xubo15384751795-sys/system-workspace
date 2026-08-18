"""Tests for the read-only four-boundary asset/check pilot."""
from __future__ import annotations

from pathlib import Path

from dagster import (
    AssetCheckResult,
    asset,
    asset_check,
    materialize,
)
from dagster._core.errors import DagsterAssetCheckFailedError
import pytest

from orchestration.assets.boundary_pilot import (
    BOUNDARY_ASSETS,
    BOUNDARY_CHECKS,
    build_admitted_evidence,
    build_decision_current,
    build_diagnostic_candidate,
    read_harvester_release,
)


def test_pilot_exposes_four_assets_and_four_blocking_checks() -> None:
    assert [asset.key.path[-1] for asset in BOUNDARY_ASSETS] == [
        "harvester_release",
        "admitted_evidence",
        "diagnostic_candidate",
        "decision_current",
    ]
    assert len(BOUNDARY_CHECKS) == 4
    assert all(spec.blocking for check in BOUNDARY_CHECKS for spec in check.specs)


def test_missing_release_is_blocked_without_creating_files(tmp_path: Path) -> None:
    release = read_harvester_release(tmp_path)
    assert release["status"] == "missing"
    assert release["manifest_exists"] is False
    assert build_admitted_evidence(release)["status"] == "blocked"
    assert build_diagnostic_candidate(build_admitted_evidence(release))["authority_mode"] == "DIAGNOSTIC_ONLY"
    assert not list(tmp_path.rglob("*"))


def test_decision_boundary_never_infers_allow(tmp_path: Path) -> None:
    candidate = {"status": "ready", "release_id": "r1", "authority_mode": "DIAGNOSTIC_ONLY"}
    decision = build_decision_current(candidate, root=tmp_path)
    assert decision["status"] == "diagnostic_only"
    assert decision["authority_mode"] == "DIAGNOSTIC_ONLY"


def test_injected_blocking_check_prevents_downstream_materialization() -> None:
    materialized: list[str] = []

    @asset(name="fixture_release")
    def fixture_release() -> dict[str, object]:
        return {"status": "failed"}

    @asset(name="fixture_admitted_evidence")
    def fixture_admitted_evidence(fixture_release: dict[str, object]) -> dict[str, object]:
        materialized.append("fixture_admitted_evidence")
        return fixture_release

    @asset_check(
        asset=fixture_release,
        name="fixture_release_admission",
        blocking=True,
    )
    def fixture_release_admission(fixture_release: dict[str, object]) -> AssetCheckResult:
        return AssetCheckResult(passed=fixture_release.get("status") == "accepted")

    with pytest.raises(DagsterAssetCheckFailedError, match="blocking asset check.*failed"):
        materialize(
            [fixture_release, fixture_admitted_evidence, fixture_release_admission]
        )

    assert materialized == []
