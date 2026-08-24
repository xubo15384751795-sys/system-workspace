from __future__ import annotations

import pytest
from dagster import materialize

from orchestration.assets.registry_block_checks import downstream_of_step
from orchestration.assets.registry_degrade_checks import (
    DEGRADE_REGISTRY_ASSETS,
    DEGRADE_REGISTRY_CHECKS,
    build_registry_degrade_defs,
    make_degraded_records,
    select_degrade_pilot_checks,
)
from orchestration.definitions import daily_job, defs
from orchestration.shadow_parity import compare_sequence_results


def _asset_paths(assets) -> list[list[str]]:
    return [asset.key.path for asset in assets]


def _check_names(checks) -> set[str]:
    return {spec.name for check in checks for spec in check.check_specs}


def test_live_registry_compiles_trade_decision_degrade_graph() -> None:
    consumers = list(downstream_of_step("trade_decision"))
    assert "risk_gate" in consumers
    assert _asset_paths(DEGRADE_REGISTRY_ASSETS) == [
        ["registry_degrade", "trade_decision"],
        *[["registry_degrade", name] for name in consumers],
    ]
    assert _check_names(DEGRADE_REGISTRY_CHECKS) == {"registry_degrade_trade_decision"}
    assert all(not spec.blocking for check in DEGRADE_REGISTRY_CHECKS for spec in check.check_specs)


def test_daily_job_does_not_execute_degrade_graph() -> None:
    node_names = {node.name for node in daily_job.nodes_in_topological_order}
    assert node_names == {"daily_job_entry"}
    defined_assets = tuple(defs.assets or ())
    defined_checks = tuple(defs.asset_checks or ())
    for asset in DEGRADE_REGISTRY_ASSETS:
        assert asset in defined_assets
    for check in DEGRADE_REGISTRY_CHECKS:
        assert check in defined_checks


def test_degrade_pilot_rejects_skip_semantics() -> None:
    document = {
        "steps": {
            "signal_consensus": {
                "status": "active",
                "failure_behavior": "block_current_readout",
                "allowed_to_affect_core_judgment": False,
                "artifact_path": "Output/current/signal_consensus.json",
                "execution": {"mode": "subprocess", "dagster_asset_check": "degrade_pilot"},
            }
        }
    }
    with pytest.raises(ValueError, match="forbids failure_behavior='block_current_readout'"):
        select_degrade_pilot_checks(document)

    document = {
        "steps": {
            "etf_refresh": {
                "status": "active",
                "failure_behavior": "research_only",
                "allowed_to_affect_core_judgment": False,
                "artifact_path": "Data/features/k_features_daily.csv",
                "execution": {"mode": "callable", "dagster_asset_check": "degrade_pilot"},
            }
        }
    }
    with pytest.raises(ValueError, match="forbids research_only"):
        select_degrade_pilot_checks(document)

    document = {
        "steps": {
            "trade_decision": {
                "status": "active",
                "failure_behavior": "hold_flat",
                "allowed_to_affect_core_judgment": True,
                "artifact_path": "Output/trade_decision/latest.json",
                "execution": {
                    "mode": "callable",
                    "dagster_asset_check": "degrade_pilot",
                    "dagster_check_blocking": True,
                },
            }
        }
    }
    with pytest.raises(ValueError, match="forbids blocking checks"):
        select_degrade_pilot_checks(document)


def test_failed_hold_flat_still_runs_risk_gate_degraded() -> None:
    seen: list[str] = []
    recorded: list[dict[str, object]] = []
    consumers = downstream_of_step("trade_decision")

    assets, checks = build_registry_degrade_defs(
        document={
            "steps": {
                "trade_decision": {
                    "status": "active",
                    "failure_behavior": "hold_flat",
                    "allowed_to_affect_core_judgment": True,
                    "artifact_path": "Output/trade_decision/latest.json",
                    "execution": {"mode": "callable", "dagster_asset_check": "degrade_pilot"},
                }
            }
        },
        read_artifact=lambda _path: {"missing": True, "status": "MISSING"},
        record_fn=lambda rows: recorded.extend(rows),
        on_consumer=seen.append,
    )
    result = materialize([*assets, *checks])

    assert result.success
    assert set(seen) == set(consumers)
    assert "risk_gate" in seen
    expected = make_degraded_records("trade_decision", tuple(sorted(consumers)))
    recorded_sorted = sorted(recorded, key=lambda row: str(row["step"]))
    assert recorded_sorted == list(expected)
    report = compare_sequence_results(list(expected), recorded_sorted)
    assert report.execution_parity == "MATCH"
    assert report.promotion_allowed is False
    risk = next(row for row in recorded if row["step"] == "risk_gate")
    assert risk["status"] == "success"
    assert risk["degraded"] is True
    assert risk["degraded_by"] == ["trade_decision"]
