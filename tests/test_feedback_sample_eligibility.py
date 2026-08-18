"""Feedback sample lifecycle and calibration-boundary contracts."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator

from system_runtime.feedback_lifecycle import (
    make_transition_event,
    validate_golden_adjudication,
    validate_lifecycle_events,
)
from system_runtime.minimum_monitoring import evaluate_minimum_monitoring


def _copy_provider_policy(root: Path) -> None:
    policy_dir = root / "configs"
    policy_dir.mkdir(parents=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[1]
        / "configs"
        / "provider_release_policy.yaml",
        policy_dir / "provider_release_policy.yaml",
    )


def test_new_sample_builder_declares_candidate_and_denies_calibration() -> None:
    from scripts.commands.weekly.build_feedback_sample_pool import _build_sample

    sample = _build_sample("2026-08-12", "event_window", "test")
    assert sample["lifecycle_state"] == "candidate"
    assert sample["eligibility"] == "ineligible"
    assert sample["allowed_to_affect_core_judgment"] is False
    assert sample["calibration_set"] is False
    assert sample["golden"] is False
    assert (
        validate_lifecycle_events(
            sample["sample_id"],
            sample["lifecycle_events"],
            current_state=sample["lifecycle_state"],
        )
        == []
    )


def test_unsafe_eligible_sample_is_blocked(tmp_path: Path) -> None:
    feedback = tmp_path / "Data" / "feedback_samples"
    feedback.mkdir(parents=True)
    (feedback / "sample_manifest.jsonl").write_text(
        '{"sample_id":"unsafe","lifecycle_state":"eligible",'
        '"eligibility":"eligible","degraded":true,"calibration_set":true}\n',
        encoding="utf-8",
    )
    result = evaluate_minimum_monitoring(tmp_path)
    check = result["checks"]["feedback_sample_eligibility"]
    assert check["status"] == "BLOCKED"
    assert any("unsafe_state" in item for item in check["violations"])


def test_missing_lifecycle_event_contract_is_blocked(tmp_path: Path) -> None:
    feedback = tmp_path / "Data" / "feedback_samples"
    feedback.mkdir(parents=True)
    (feedback / "sample_manifest.jsonl").write_text(
        '{"sample_id":"legacy","lifecycle_state":"candidate",'
        '"eligibility":"ineligible"}\n',
        encoding="utf-8",
    )
    result = evaluate_minimum_monitoring(tmp_path)
    check = result["checks"]["feedback_sample_eligibility"]
    assert check["status"] == "BLOCKED"
    assert any("missing_lifecycle_events" in item for item in check["violations"])


def test_cross_run_and_future_leak_are_blocked_for_candidate_samples(tmp_path: Path) -> None:
    feedback = tmp_path / "Data" / "feedback_samples"
    feedback.mkdir(parents=True)
    records = []
    for sample_id, field in (
        ("candidate-cross-run", "cross_run"),
        ("candidate-future-leak", "future_leak"),
    ):
        records.append(
            {
                "sample_id": sample_id,
                "lifecycle_state": "candidate",
                "eligibility": "ineligible",
                field: True,
                "lifecycle_events": [
                    make_transition_event(
                        sample_id=sample_id,
                        from_state=None,
                        to_state="candidate",
                        owner="test",
                        occurred_at="2026-08-12T00:00:00Z",
                        evidence=["fixture"],
                    )
                ],
            }
        )
    (feedback / "sample_manifest.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    check = evaluate_minimum_monitoring(tmp_path)["checks"][
        "feedback_sample_eligibility"
    ]
    assert check["status"] == "BLOCKED"
    assert "candidate-cross-run:cross_run_or_future_leak" in check["violations"]
    assert "candidate-future-leak:cross_run_or_future_leak" in check["violations"]


def test_hold_degraded_and_watch_like_states_cannot_enter_calibration(tmp_path: Path) -> None:
    feedback = tmp_path / "Data" / "feedback_samples"
    feedback.mkdir(parents=True)
    sample_id = "degraded-eligible"
    events = [
        make_transition_event(
            sample_id=sample_id,
            from_state=None,
            to_state="candidate",
            owner="test",
            occurred_at="2026-08-12T00:00:00Z",
            evidence=["fixture"],
        ),
        make_transition_event(
            sample_id=sample_id,
            from_state="candidate",
            to_state="eligible",
            owner="test",
            occurred_at="2026-08-12T00:01:00Z",
            evidence=["fixture_review"],
        ),
    ]
    (feedback / "sample_manifest.jsonl").write_text(
        json.dumps(
            {
                "sample_id": sample_id,
                "lifecycle_state": "eligible",
                "eligibility": "eligible",
                "lifecycle_events": events,
                "decision": "ACTIVE_WATCH",
                "sizing_mode": "HOLD_DEGRADED",
                "sample_validity": "DEGRADED",
                "calibration_set": False,
                "golden": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path)
    check = result["checks"]["feedback_sample_eligibility"]
    assert check["status"] == "BLOCKED"
    assert f"{sample_id}:unsafe_state" in check["violations"]


def test_accepted_is_not_golden_and_remains_separate_from_calibration_set(
    tmp_path: Path,
) -> None:
    _copy_provider_policy(tmp_path)
    feedback = tmp_path / "Data" / "feedback_samples"
    feedback.mkdir(parents=True)
    sample_id = "accepted-not-golden"
    events = [
        make_transition_event(
            sample_id=sample_id,
            from_state=None,
            to_state="candidate",
            owner="test",
            occurred_at="2026-08-12T00:00:00Z",
            evidence=["fixture"],
        ),
        make_transition_event(
            sample_id=sample_id,
            from_state="candidate",
            to_state="eligible",
            owner="test",
            occurred_at="2026-08-12T00:01:00Z",
            evidence=["eligibility_review"],
        ),
        make_transition_event(
            sample_id=sample_id,
            from_state="eligible",
            to_state="reviewed",
            owner="test",
            occurred_at="2026-08-12T00:02:00Z",
            evidence=["human_review"],
        ),
        make_transition_event(
            sample_id=sample_id,
            from_state="reviewed",
            to_state="accepted",
            owner="test",
            occurred_at="2026-08-12T00:03:00Z",
            evidence=["acceptance_decision"],
        ),
    ]
    (feedback / "sample_manifest.jsonl").write_text(
        json.dumps(
            {
                "sample_id": sample_id,
                "lifecycle_state": "accepted",
                "eligibility": "eligible",
                "provider_status": "refreshed",
                "allowed_to_affect_core_judgment": False,
                "calibration_set": False,
                "golden": False,
                "lifecycle_events": events,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    check = evaluate_minimum_monitoring(tmp_path)["checks"][
        "feedback_sample_eligibility"
    ]
    assert check["status"] == "PASS"
    assert check["violations"] == []


def test_golden_requires_versioned_adjudication_contract(tmp_path: Path) -> None:
    feedback = tmp_path / "Data" / "feedback_samples"
    feedback.mkdir(parents=True)
    sample_id = "golden-needs-adjudication"
    events = [
        make_transition_event(
            sample_id=sample_id,
            from_state=None,
            to_state="candidate",
            owner="test",
            occurred_at="2026-08-12T00:00:00Z",
            evidence=["fixture"],
        )
    ]
    (feedback / "sample_manifest.jsonl").write_text(
        json.dumps(
            {
                "sample_id": sample_id,
                "lifecycle_state": "candidate",
                "eligibility": "ineligible",
                "golden": True,
                "golden_adjudication": {"criteria_version": "golden.v1"},
                "lifecycle_events": events,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    check = evaluate_minimum_monitoring(tmp_path)["checks"][
        "feedback_sample_eligibility"
    ]
    assert check["status"] == "BLOCKED"
    assert f"{sample_id}:golden_missing_adjudicator" in check["violations"]
    assert f"{sample_id}:golden_missing_occurred_at" in check["violations"]
    assert f"{sample_id}:golden_missing_evidence" in check["violations"]
    assert validate_golden_adjudication(
        {
            "criteria_version": "golden.v1",
            "adjudicator": "reviewer",
            "occurred_at": "2026-08-12T00:04:00Z",
            "evidence": ["review_record"],
        }
    ) == []


def test_feedback_schema_requires_separate_versioned_golden_adjudication() -> None:
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "protocols" / "feedback_sample.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    base = {
        "schema_version": "feedback_sample.v1",
        "sample_id": "schema-golden",
        "as_of_date": "2026-08-12",
        "sample_type": "random",
        "generated_at": "2026-08-12T00:00:00Z",
        "golden": True,
        "golden_adjudication": {"criteria_version": "golden.v1"},
    }
    assert list(validator.iter_errors(base))
    valid = {
        **base,
        "golden_adjudication": {
            "criteria_version": "golden.v1",
            "adjudicator": "reviewer",
            "occurred_at": "2026-08-12T00:04:00Z",
            "evidence": ["review_record"],
        },
    }
    assert list(validator.iter_errors(valid)) == []
    assert list(validator.iter_errors({**valid, "cross_run": True}))
    assert list(validator.iter_errors({**valid, "future_leak": True}))
