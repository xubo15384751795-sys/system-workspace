from __future__ import annotations

import pytest
from dagster import materialize
from dagster._core.errors import DagsterAssetCheckFailedError

from orchestration.assets.registry_block_checks import (
    BLOCK_REGISTRY_ASSETS,
    BLOCK_REGISTRY_CHECKS,
    build_registry_block_defs,
    make_blocked_upstream_records,
    select_blocking_pilot_checks,
)
from orchestration.definitions import daily_job, defs
from orchestration.shadow_parity import compare_sequence_results


def _asset_paths(assets) -> list[list[str]]:
    return [asset.key.path for asset in assets]


def _check_names(checks) -> set[str]:
    return {spec.name for check in checks for spec in check.check_specs}


def test_live_registry_compiles_signal_consensus_block_graph() -> None:
    assert _asset_paths(BLOCK_REGISTRY_ASSETS) == [
        ["registry_block", "signal_consensus"],
        ["registry_block", "freshness_validator"],
    ]
    assert _check_names(BLOCK_REGISTRY_CHECKS) == {"registry_block_signal_consensus"}
    assert all(spec.blocking for check in BLOCK_REGISTRY_CHECKS for spec in check.check_specs)


def test_daily_job_does_not_execute_block_graph() -> None:
    node_names = {node.name for node in daily_job.nodes_in_topological_order}
    assert node_names == {"daily_job_entry"}
    defined_assets = tuple(defs.assets or ())
    defined_checks = tuple(defs.asset_checks or ())
    for asset in BLOCK_REGISTRY_ASSETS:
        assert asset in defined_assets
    for check in BLOCK_REGISTRY_CHECKS:
        assert check in defined_checks


def test_blocking_pilot_rejects_soft_or_core_judgment_steps() -> None:
    document = {
        "steps": {
            "build_data_gaps": {
                "status": "active",
                "failure_behavior": "continue_with_warning",
                "allowed_to_affect_core_judgment": False,
                "artifact_path": "Output/current/data_gaps.json",
                "execution": {"mode": "subprocess", "dagster_asset_check": "blocking_pilot"},
            }
        }
    }
    with pytest.raises(ValueError, match="forbids failure_behavior='continue_with_warning'"):
        select_blocking_pilot_checks(document)

    document = {
        "steps": {
            "harvester": {
                "status": "active",
                "failure_behavior": "block_core_judgment",
                "allowed_to_affect_core_judgment": True,
                "artifact_path": "Data/harvester/exports/latest/catalog.json",
                "execution": {"mode": "subprocess", "dagster_asset_check": "blocking_pilot"},
            }
        }
    }
    with pytest.raises(ValueError, match="forbids core-judgment"):
        select_blocking_pilot_checks(document)


def test_blocking_pilot_requires_a_dag_consumer() -> None:
    with pytest.raises(ValueError, match="requires at least one DAG consumer"):
        build_registry_block_defs(
            document={
                "steps": {
                    "paper_portfolio": {
                        "status": "active",
                        "failure_behavior": "decision_adjacent_block",
                        "allowed_to_affect_core_judgment": False,
                        "artifact_path": "Output/paper_portfolio/latest.json",
                        "execution": {
                            "mode": "subprocess",
                            "dagster_asset_check": "blocking_pilot",
                        },
                    }
                }
            }
        )


def test_failed_block_check_skips_downstream_and_keeps_blocked_upstream() -> None:
    seen: list[str] = []
    recorded: list[dict[str, object]] = []

    assets, checks = build_registry_block_defs(
        document={
            "steps": {
                "signal_consensus": {
                    "status": "active",
                    "failure_behavior": "block_current_readout",
                    "allowed_to_affect_core_judgment": False,
                    "artifact_path": "Output/current/signal_consensus.json",
                    "execution": {
                        "mode": "subprocess",
                        "dagster_asset_check": "blocking_pilot",
                    },
                }
            }
        },
        read_artifact=lambda _path: {"missing": True, "status": "MISSING"},
        record_fn=lambda rows: recorded.extend(rows),
        on_consumer=seen.append,
    )
    with pytest.raises(DagsterAssetCheckFailedError, match="blocking asset check.*failed"):
        materialize([*assets, *checks])

    expected = make_blocked_upstream_records("signal_consensus", ("freshness_validator",))
    assert seen == []
    assert recorded == list(expected)
    report = compare_sequence_results(list(expected), recorded)
    assert report.execution_parity == "MATCH"
    assert report.promotion_allowed is False
