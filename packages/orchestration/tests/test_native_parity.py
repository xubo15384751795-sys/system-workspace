from __future__ import annotations

from orchestration.native_parity import build_native_parity_report, compare_native_report


def test_native_parity_ignores_only_generation_timestamp() -> None:
    native = {"generated_at": "2026-08-25T00:00:00Z", "grade": "D", "items": [1, 2]}
    legacy = {"generated_at": "2026-08-25T00:01:00Z", "grade": "D", "items": [1, 2]}

    report = compare_native_report(
        step_id="evidence_grade_report",
        native_report=native,
        legacy_report=legacy,
    )

    assert report["status"] == "MATCH"
    assert report["promotion_allowed"] is False
    assert report["ignored_fields"] == ["generated_at"]


def test_native_parity_never_treats_missing_legacy_artifact_as_match() -> None:
    report = compare_native_report(
        step_id="build_data_gaps",
        native_report={"gaps": []},
        legacy_report=None,
    )

    assert report["status"] == "LEGACY_MISSING"
    aggregate = build_native_parity_report({"build_data_gaps": report})
    assert aggregate["status"] == "INCOMPLETE"
    assert aggregate["promotion_allowed"] is False


def test_native_parity_surfaces_payload_mismatch() -> None:
    report = compare_native_report(
        step_id="build_artifact_registry",
        native_report={"artifact_count": 2},
        legacy_report={"artifact_count": 3},
    )

    assert report["status"] == "MISMATCH"
    assert report["native_digest"] != report["legacy_digest"]
    assert report["native_report"] == {"artifact_count": 2}
