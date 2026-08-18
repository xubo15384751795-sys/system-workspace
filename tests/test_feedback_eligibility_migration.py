"""Legacy feedback eligibility migration remains fail-closed."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.commands.weekly.migrate_feedback_eligibility import migrate_manifest
from system_runtime.feedback_lifecycle import validate_lifecycle_events
from system_runtime.minimum_monitoring import evaluate_minimum_monitoring


def test_dry_run_classifies_without_writing(tmp_path: Path) -> None:
    manifest = tmp_path / "sample_manifest.jsonl"
    original = {"sample_id": "legacy-1", "review_label": "needs_review"}
    manifest.write_text(json.dumps(original) + "\n", encoding="utf-8")

    result = migrate_manifest(manifest)

    assert result["status"] == "READY_TO_APPLY"
    assert result["records_to_classify"] == 1
    assert json.loads(manifest.read_text(encoding="utf-8")) == original
    assert not list(tmp_path.glob("*.bak"))


def test_apply_is_backuped_and_stays_ineligible(tmp_path: Path) -> None:
    manifest = tmp_path / "sample_manifest.jsonl"
    manifest.write_text(
        json.dumps({"sample_id": "legacy-1"}) + "\n", encoding="utf-8"
    )

    result = migrate_manifest(
        manifest,
        apply=True,
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )
    record = json.loads(manifest.read_text(encoding="utf-8"))

    assert result["status"] == "APPLIED"
    assert Path(result["backup"]).is_file()
    assert record["lifecycle_state"] == "candidate"
    assert record["eligibility"] == "ineligible"
    assert record["calibration_set"] is False
    assert record["golden"] is False
    assert record["allowed_to_affect_core_judgment"] is False
    assert (
        validate_lifecycle_events(
            record["sample_id"],
            record["lifecycle_events"],
            current_state=record["lifecycle_state"],
        )
        == []
    )


def test_applied_migration_satisfies_structural_feedback_monitor(tmp_path: Path) -> None:
    feedback = tmp_path / "Data" / "feedback_samples"
    feedback.mkdir(parents=True)
    manifest = feedback / "sample_manifest.jsonl"
    manifest.write_text(json.dumps({"sample_id": "legacy-1"}) + "\n", encoding="utf-8")

    migrate_manifest(
        manifest,
        apply=True,
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )
    result = evaluate_minimum_monitoring(tmp_path)
    check = result["checks"]["feedback_sample_eligibility"]
    assert check["status"] == "PASS"


def test_apply_repairs_record_that_has_fields_but_no_lifecycle_events(tmp_path: Path) -> None:
    manifest = tmp_path / "sample_manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "sample_id": "partial-legacy",
                "lifecycle_state": "candidate",
                "eligibility": "ineligible",
                "eligibility_reason_codes": ["LEGACY_RECORD_CLASSIFIED"],
                "allowed_to_affect_core_judgment": False,
                "calibration_set": False,
                "golden": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = migrate_manifest(
        manifest,
        apply=True,
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )
    record = json.loads(manifest.read_text(encoding="utf-8"))

    assert result["records_to_classify"] == 1
    assert validate_lifecycle_events(
        record["sample_id"],
        record["lifecycle_events"],
        current_state=record["lifecycle_state"],
    ) == []
