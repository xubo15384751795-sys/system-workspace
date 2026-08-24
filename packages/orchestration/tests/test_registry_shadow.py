from __future__ import annotations

import pytest
from dagster import materialize

from orchestration.assets.registry_shadow import (
    SHADOW_REGISTRY_ASSETS,
    build_shadow_registry_assets,
    compare_shadow_step,
    select_shadow_pilot_steps,
)
from orchestration.definitions import daily_job, defs


def test_live_registry_compiles_one_shadow_pilot_leaf() -> None:
    assert [asset.key.path for asset in SHADOW_REGISTRY_ASSETS] == [
        ["registry_shadow", "build_data_gaps"]
    ]


def test_daily_job_does_not_materialize_shadow_assets() -> None:
    node_names = {node.name for node in daily_job.nodes_in_topological_order}
    assert node_names == {"daily_job_entry"}
    assert SHADOW_REGISTRY_ASSETS[0] in tuple(defs.assets or ())


def test_shadow_pilot_rejects_blocking_or_judgment_steps() -> None:
    document = {
        "steps": {
            "trade_decision": {
                "status": "active",
                "failure_behavior": "hold_flat",
                "allowed_to_affect_core_judgment": False,
                "execution": {"mode": "subprocess", "dagster_asset": "shadow_pilot"},
            }
        }
    }
    with pytest.raises(ValueError, match="forbids failure_behavior='hold_flat'"):
        select_shadow_pilot_steps(document)

    document = {
        "steps": {
            "claim_evaluator": {
                "status": "active",
                "failure_behavior": "lower_claim_ceiling",
                "allowed_to_affect_core_judgment": False,
                "execution": {"mode": "subprocess", "dagster_asset": "shadow_pilot"},
            }
        }
    }
    with pytest.raises(ValueError, match="forbids failure_behavior='lower_claim_ceiling'"):
        select_shadow_pilot_steps(document)

    document = {
        "steps": {
            "judgment_layer": {
                "status": "active",
                "failure_behavior": "continue_with_warning",
                "allowed_to_affect_core_judgment": True,
                "execution": {"mode": "subprocess", "dagster_asset": "shadow_pilot"},
            }
        }
    }
    with pytest.raises(ValueError, match="forbids core-judgment"):
        select_shadow_pilot_steps(document)


def test_shadow_asset_wraps_registry_runner_without_changing_behavior() -> None:
    calls: list[str] = []

    def fake_run(step_id: str, **_kwargs):
        calls.append(step_id)
        return {"step": step_id, "status": "success"}

    assets = build_shadow_registry_assets(
        document={
            "steps": {
                "build_data_gaps": {
                    "status": "active",
                    "failure_behavior": "continue_with_warning",
                    "allowed_to_affect_core_judgment": False,
                    "execution": {"mode": "subprocess", "dagster_asset": "shadow_pilot"},
                }
            }
        },
        run_step=fake_run,
    )
    result = materialize(list(assets))
    assert result.success
    assert calls == ["build_data_gaps"]
    payload = result.output_for_node("registry_shadow__build_data_gaps")
    assert payload["authority"] == "shadow_only"
    assert payload["failure_behavior"] == "continue_with_warning"
    report = compare_shadow_step(
        {"step": "build_data_gaps", "status": "success"},
        payload,
    )
    assert report.execution_parity == "MATCH"
    assert report.promotion_allowed is False
    assert report.authority == "shadow_only"


def test_shadow_parity_stops_on_status_or_degraded_mismatch() -> None:
    report = compare_shadow_step(
        {"step": "build_data_gaps", "status": "success", "blocked_by": [], "degraded": False},
        {
            "step": "build_data_gaps",
            "status": "success",
            "blocked_by": ["upstream"],
            "degraded": True,
        },
    )
    assert report.execution_parity == "MISMATCH"
    assert report.promotion_allowed is False
