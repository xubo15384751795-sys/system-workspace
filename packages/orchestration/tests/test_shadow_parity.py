"""Contract tests for the non-authoritative SYS-21 shadow comparator."""
from __future__ import annotations

from orchestration.shadow_parity import compare_sequence_results


def _result(step: str, status: str = "success") -> dict[str, object]:
    return {"step": step, "status": status, "duration_s": 0}


def test_matching_execution_without_lineage_is_not_claimed_as_migration() -> None:
    report = compare_sequence_results(
        [_result("harvester"), _result("judgment")],
        [_result("harvester"), _result("judgment")],
        plan_digest="plan-test",
    )

    assert report.execution_parity == "MATCH"
    assert report.canonical_lineage_parity == "NOT_PRESENT"
    assert report.status == "EXECUTION_MATCH_CANONICAL_UNAVAILABLE"
    assert report.authority == "shadow_only"
    assert report.promotion_allowed is False
    assert report.to_dict()["plan_digest"] == "plan-test"


def test_execution_divergence_is_fail_closed() -> None:
    report = compare_sequence_results(
        [_result("harvester"), _result("judgment")],
        [_result("harvester"), _result("judgment", "blocked_upstream")],
    )

    assert report.execution_parity == "MISMATCH"
    assert report.status == "MISMATCH"
    assert any(item["kind"] == "step_result" for item in report.mismatches)


def test_full_canonical_lineage_must_match_on_both_paths() -> None:
    ids = {
        "observation_id": "obs_00000000000000000000000000000001",
        "measurement_id": "mea_00000000000000000000000000000001",
        "evidence_id": "evd_00000000000000000000000000000001",
        "claim_id": "clm_00000000000000000000000000000001",
    }
    left = [{"step": "framework", "status": "success", "canonical_ids": ids}]
    right = [{"step": "framework", "status": "success", "canonical_ids": dict(ids)}]

    report = compare_sequence_results(left, right)

    assert report.execution_parity == "MATCH"
    assert report.canonical_lineage_parity == "MATCH"
    assert report.status == "PASS"


def test_canonical_lineage_drift_is_visible_even_when_steps_match() -> None:
    left = [
        {
            "step": "framework",
            "status": "success",
            "canonical_ids": {
                "observation_id": "obs_00000000000000000000000000000001",
                "measurement_id": "mea_00000000000000000000000000000001",
                "evidence_id": "evd_00000000000000000000000000000001",
                "claim_id": "clm_00000000000000000000000000000001",
            },
        }
    ]
    right = [
        {
            "step": "framework",
            "status": "success",
            "canonical_ids": {
                "observation_id": "obs_00000000000000000000000000000002",
                "measurement_id": "mea_00000000000000000000000000000002",
                "evidence_id": "evd_00000000000000000000000000000002",
                "claim_id": "clm_00000000000000000000000000000002",
            },
        }
    ]

    report = compare_sequence_results(left, right)

    assert report.execution_parity == "MATCH"
    assert report.canonical_lineage_parity == "MISMATCH"
    assert report.status == "MISMATCH"
    assert report.promotion_allowed is False
