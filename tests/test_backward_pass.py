from __future__ import annotations

from scripts.commands.weekly.backward_pass import build_report


def test_historical_rows_are_not_given_fabricated_credit() -> None:
    report = build_report(
        [{"date": "2026-06-16", "market_forward_outcome": {"outcomes": {}}}],
        {},
    )

    assert report["status"] == "DECISION_REQUIRED"
    assert report["coverage"]["historical_unidentifiable_entries"] == 1
    assert report["credits"] == []
    assert report["credit_can_grant_authority"] is False


def test_credit_stays_ineligible_below_approved_sample_floor() -> None:
    trace = {
        "schema_version": "decision_learning_trace.v1",
        "authority": "shadow_only",
        "credit_can_grant_authority": False,
        "nodes": [
            {
                "node_id": "velocity_state",
                "parents": [],
                "baseline_status": "DECISION_REQUIRED",
                "value": {"velocity_gate": {"state": "FULL"}, "sigma_vector": {}},
            },
            {
                "node_id": "effective_sizing",
                "parents": ["velocity_state"],
                "baseline_status": "DERIVED",
                "value": 1.0,
            },
        ],
    }
    entry = {
        "date": "2026-07-17",
        "decision_fingerprint": "abc",
        "learning_trace": trace,
        "market_forward_outcome": {
            "outcomes": {"1w": {"metrics": {"SPY": {"return_pct": 2.0}}}}
        },
    }
    policy = {
        "outcome_credit": {
            "enabled": True,
            "objective": "realized_utility",
            "horizon": "1w",
            "market": "SPY",
            "minimum_samples": 5,
            "node_baselines": {
                "velocity_state": {"velocity_gate": {"state": "EXIT"}, "sigma_vector": {}}
            },
        }
    }

    report = build_report([entry], policy)

    assert report["status"] == "INSUFFICIENT_SAMPLES"
    assert report["sample_count"] == 1
    assert report["eligible_to_affect_review_priority"] is False
    assert report["eligible_to_grant_authority"] is False


def test_shapley_waits_for_and_runs_at_approved_sample_floor() -> None:
    trace = {
        "schema_version": "decision_learning_trace.v1",
        "authority": "shadow_only",
        "credit_can_grant_authority": False,
        "nodes": [
            {
                "node_id": "velocity_state",
                "parents": [],
                "baseline_status": "DECISION_REQUIRED",
                "value": {"velocity_gate": {"state": "FULL"}, "sigma_vector": {}},
            },
            {
                "node_id": "effective_sizing",
                "parents": ["velocity_state"],
                "baseline_status": "DERIVED",
                "value": 1.0,
            },
        ],
    }
    entries = [
        {
            "date": f"2026-08-{index + 1:02d}",
            "decision_fingerprint": str(index),
            "learning_trace": trace,
            "market_forward_outcome": {
                "outcomes": {"1w": {"metrics": {"SPY": {"return_pct": 2.0}}}}
            },
        }
        for index in range(30)
    ]
    policy = {
        "outcome_credit": {
            "enabled": True,
            "objective": "directional_opportunity_loss",
            "deadband_pct": 0.5,
            "horizon": "1w",
            "market": "SPY",
            "minimum_samples": 20,
            "shapley_minimum_samples": 30,
            "shapley_top_nodes": 3,
            "node_baselines": {
                "velocity_state": {"velocity_gate": {"state": "EXIT"}, "sigma_vector": {}}
            },
        }
    }

    report = build_report(entries, policy)

    assert report["status"] == "ELIGIBLE_FOR_REVIEW_PRIORITY"
    assert report["shapley"]["status"] == "EVALUATED"
    assert report["shapley"]["node_ids"] == ["velocity_state"]
    assert report["eligible_to_grant_authority"] is False
