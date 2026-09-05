"""Acceptance tests for the side-effect-free plan/apply boundary."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from system_runtime.paths import WorkspacePaths
from system_runtime.plan_apply import (
    PlanApplyError,
    build_plan,
    evidence_digest,
    load_plan,
    validate_apply,
    validate_plan,
    write_plan,
)

ROOT = Path(__file__).resolve().parents[1]
_UPDATED_AT_RE = re.compile(r"updated_at:\s*'[0-9-]+'")


def _bump_registry_updated_at(registry: Path) -> None:
    text = registry.read_text(encoding="utf-8")
    bumped, count = _UPDATED_AT_RE.subn("updated_at: '2099-01-01'", text, count=1)
    if count != 1 or bumped == text:
        raise AssertionError(f"{registry} has no replaceable updated_at field")
    registry.write_text(bumped, encoding="utf-8")


def _workspace(tmp_path: Path) -> WorkspacePaths:
    root = tmp_path / "workspace"
    (root / "governance").mkdir(parents=True)
    (root / "protocols").mkdir()
    shutil.copy2(
        ROOT / "governance/daily_pipeline_registry.yaml",
        root / "governance/daily_pipeline_registry.yaml",
    )
    shutil.copy2(
        ROOT / "protocols/pipeline_spec.schema.json",
        root / "protocols/pipeline_spec.schema.json",
    )
    return WorkspacePaths(root=root)


def test_plan_phase_does_not_create_data_or_output(tmp_path: Path) -> None:
    paths = _workspace(tmp_path)
    artifact = build_plan(paths)

    assert len(artifact.plan_id) == 64
    assert not (paths.root / "Data").exists()
    assert not (paths.root / "Output").exists()


def test_plan_round_trip_and_current_validation(tmp_path: Path) -> None:
    paths = _workspace(tmp_path)
    artifact = build_plan(paths)
    target = write_plan(artifact, paths.root / ".system/plans/plan.json", root=paths.root)

    loaded = load_plan(target)
    result = validate_plan(loaded, paths)

    assert result["stale"] is False
    assert result["plan_id"] == artifact.plan_id
    assert not (paths.root / "Data").exists()
    assert not (paths.root / "Output").exists()


def test_policy_change_rejects_saved_plan(tmp_path: Path) -> None:
    paths = _workspace(tmp_path)
    artifact = build_plan(paths)
    target = write_plan(artifact, paths.root / ".system/plans/plan.json", root=paths.root)
    _bump_registry_updated_at(paths.root / "governance/daily_pipeline_registry.yaml")

    result = validate_plan(load_plan(target), paths)

    assert result["stale"] is True
    assert "policy_digest" in result["differences"]


def test_plan_cannot_be_written_under_data_or_output(tmp_path: Path) -> None:
    paths = _workspace(tmp_path)
    artifact = build_plan(paths)

    with pytest.raises(PlanApplyError, match="Data/ or Output/"):
        write_plan(artifact, paths.root / "Output/plan.json", root=paths.root)


def test_apply_requires_matching_evidence_and_admission(tmp_path: Path) -> None:
    paths = _workspace(tmp_path)
    artifact = build_plan(paths)
    plan_path = write_plan(artifact, paths.root / ".system/plans/plan.json", root=paths.root)

    evidence_path = paths.root / ".system/evidence.json"
    evidence_body = {
        "schema_version": "system.evidence.v1",
        "plan_digest": artifact.plan_digest,
        "run_id": "run-test",
        "artifacts": {"panel": {"status": "refreshed"}},
    }
    evidence_digest_value = hashlib.sha256(
        json.dumps(evidence_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence_path.write_text(
        json.dumps({**evidence_body, "evidence_digest": evidence_digest_value}) + "\n",
        encoding="utf-8",
    )
    assert evidence_digest(evidence_path) == evidence_digest_value

    admission_body = {
        "schema_version": "system.publish_admission.v1",
        "run_id": "run-test",
        "integrity_verdict": "PASS",
        "authority_verdict": "DIAGNOSTIC_ONLY",
        "diagnostic_verdict": "PASS",
        "plan_digest": artifact.plan_digest,
        "evidence_digest": evidence_digest_value,
        "generation_digest": "a" * 64,
    }
    admission_digest = hashlib.sha256(
        json.dumps(admission_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    admission_path = paths.root / ".system/admission.json"
    admission_path.write_text(
        json.dumps({**admission_body, "admission_digest": admission_digest}) + "\n",
        encoding="utf-8",
    )

    result = validate_apply(
        load_plan(plan_path),
        paths,
        evidence_path=evidence_path,
        admission_path=admission_path,
    )

    assert result["status"] == "READY"
    assert result["would_write"] is False
    assert result["authority_verdict"] == "DIAGNOSTIC_ONLY"


def test_apply_rejects_stale_plan_before_reading_evidence(tmp_path: Path) -> None:
    paths = _workspace(tmp_path)
    artifact = build_plan(paths)
    plan_path = write_plan(artifact, paths.root / ".system/plans/plan.json", root=paths.root)
    _bump_registry_updated_at(paths.root / "governance/daily_pipeline_registry.yaml")

    with pytest.raises(PlanApplyError, match="stale plan rejected"):
        validate_apply(
            load_plan(plan_path),
            paths,
            evidence_path=paths.root / "missing-evidence.json",
            admission_path=paths.root / "missing-admission.json",
        )
