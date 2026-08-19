"""Claim ladder M/D persistence — unit tests for Tier 2 eligibility."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB_SRC = ROOT / "packages" / "workbench" / "src"
if str(WB_SRC) not in sys.path:
    sys.path.insert(0, str(WB_SRC))

from workbench.judgment.claim_ladder import _check_persistence, evaluate_claim_tier


def test_persistence_counts_current_run_only():
    ok, count = _check_persistence([], "stress_relief")
    assert count == 1
    assert ok is False


def test_persistence_two_runs_same_direction():
    history = [{"md_direction": "stress_relief", "run_id": "prev"}]
    ok, count = _check_persistence(history, "stress_relief")
    assert count == 2
    assert ok is True


def test_persistence_breaks_on_direction_change():
    history = [
        {"md_direction": "stress_building", "run_id": "prev"},
        {"md_direction": "stress_relief", "run_id": "older"},
    ]
    ok, count = _check_persistence(history, "stress_relief")
    assert count == 1
    assert ok is False


def test_neutral_direction_never_persists():
    ok, count = _check_persistence(
        [{"md_direction": "neutral"}],
        "neutral",
    )
    assert count == 0
    assert ok is False


def test_claim_ladder_does_not_parse_rendered_meaning_for_md():
    tier = evaluate_claim_tier(
        judgment={"meaning": ["M=9.0, D=9.0"], "md_values": {"M": 0.0, "D": 0.0}},
        caselab={"match_quality": {"label": "strong", "top_score": 0.80}},
    )

    assert tier.md_direction == "neutral"
    assert tier.md_values == {"M": 0.0, "D": 0.0}


def test_tier_three_requires_policy_replay_and_review_evidence():
    tier = evaluate_claim_tier(
        judgment={"md_values": {"M": 0.6, "D": 0.5}},
        caselab={
            "match_quality": {"label": "strong", "top_score": 0.80},
            "mechanism_context": {"mechanism_types": ["anchor_drift"]},
        },
        run_history=[
            {"md_direction": "stress_building", "run_id": "run-2"},
            {"md_direction": "stress_building", "run_id": "run-1"},
        ],
        evidence_context={
            "data_quality_grade": "B",
            "hmm_conflict": False,
            "hmm_conflict_consecutive_runs": 0,
            "md_direction_reversed": False,
            "invalidation_condition_count": 1,
            "invalidation_triggered_and_recorded": 1,
            "replay_evaluation_count": 30,
            "replay_useful_rate": 0.55,
            "replay_false_positive_rate": 0.40,
            "mechanism_misleading_rate": 0.30,
            "learning_hub_unresolved_high_severity": 0,
            "tier2_duration_runs": 3,
        },
    )

    assert tier.tier == 3
    assert tier.label == "operational_research"
    assert tier.policy_version == "claim_ladder_policy.v1"
