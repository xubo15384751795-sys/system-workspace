from __future__ import annotations

import pytest

from system_runtime.credit_assignment import (
    ablation_marginals,
    build_trade_learning_trace,
    exact_shapley_loss_reduction,
    join_activation_costs,
    validate_trace,
)


def test_trade_trace_is_ordered_shadow_dag_with_activation_metrics() -> None:
    trace = build_trade_learning_trace(
        date="2026-07-17",
        quality_inputs={
            "k_verdict": "PASS",
            "x_verdict": "FAIL",
            "hmm_grade": "ADEQUATE",
            "caselab_label": "usable",
            "has_approved_paper": True,
            "paper_stale": False,
            "promotion_hard_blocked": False,
            "proxy_quality": None,
        },
        velocity_gate={"state": "FULL"},
        sigma_vector={"n_deteriorating": 1},
        stance="RISK_ON",
        size=0.5,
        effective_size=0.5,
        run_id="run-123",
    )

    assert validate_trace(trace) == []
    assert trace["authority"] == "shadow_only"
    assert trace["credit_can_grant_authority"] is False
    assert trace["activation"]["active_count"] < trace["activation"]["total_count"]
    assert trace["activation"]["cost_status"] == "JOINABLE_FROM_RUN_STEPS"
    assert trace["nodes"][1]["producer_step"] == "k_measurement_gate"


def test_ablation_reports_loss_reduction_without_authority() -> None:
    def replay(inputs: dict[str, float]) -> dict[str, float]:
        return {"prediction": inputs["a"] + inputs["b"]}

    def loss(output: dict[str, float]) -> float:
        return (output["prediction"] - 3.0) ** 2
    result = ablation_marginals(
        {"a": 1.0, "b": 2.0},
        baselines={"a": 0.0, "b": 0.0},
        replay=replay,
        loss=loss,
    )

    assert result["actual_loss"] == 0.0
    assert [row["loss_reduction"] for row in result["credits"]] == [1.0, 4.0]
    assert result["credit_can_grant_authority"] is False


def test_exact_shapley_sums_to_total_loss_reduction() -> None:
    def replay(inputs: dict[str, float]) -> dict[str, float]:
        return {"prediction": inputs["a"] + inputs["b"]}

    def loss(output: dict[str, float]) -> float:
        return (output["prediction"] - 3.0) ** 2
    credits = exact_shapley_loss_reduction(
        {"a": 1.0, "b": 2.0},
        baselines={"a": 0.0, "b": 0.0},
        node_ids=["a", "b"],
        replay=replay,
        loss=loss,
    )

    assert sum(credits.values()) == pytest.approx(9.0)
    assert credits == pytest.approx({"a": 3.0, "b": 6.0})


def test_exact_shapley_rejects_unbounded_computation() -> None:
    values = {str(index): 1 for index in range(11)}
    with pytest.raises(ValueError, match="limited to 10"):
        exact_shapley_loss_reduction(
            values,
            baselines={key: 0 for key in values},
            node_ids=values,
            replay=lambda inputs: inputs,
            loss=lambda output: 0.0,
        )


def test_activation_costs_deduplicate_shared_producer_steps() -> None:
    trace = {
        "run_id": "run-1",
        "nodes": [
            {"node_id": "a", "producer_step": "trade_decision", "active": True},
            {"node_id": "b", "producer_step": "trade_decision", "active": True},
            {"node_id": "c", "producer_step": "k_gate", "active": True},
            {"node_id": "inactive", "producer_step": "x_gate", "active": False},
        ],
    }
    costs = join_activation_costs(
        trace,
        [
            {"step": "trade_decision", "duration_s": 4.0},
            {"step": "k_gate", "duration_s": 2.0},
        ],
    )

    assert costs["unique_producer_cost_s"] == 6.0
    assert costs["unique_active_producer_steps"] == 2
    assert [row["attributed_duration_s"] for row in costs["node_costs"]] == [2.0, 2.0, 2.0]
