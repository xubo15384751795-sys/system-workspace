from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from dagster import materialize
from dagster._core.errors import DagsterAssetCheckFailedError

from orchestration.assets.native_adjacent import (
    NATIVE_ADJACENT_ASSETS,
    NATIVE_ADJACENT_CHECKS,
    build_native_adjacent_assets,
    build_native_adjacent_checks,
    native_adjacent_payload,
)
from orchestration.definitions import (
    defs,
    native_adjacent_pilot_job,
    native_adjacent_pilot_schedule,
)
from orchestration.native_adjacent_boundaries import (
    NATIVE_ADJACENT_BOUNDARY_STEPS,
    execute_native_adjacent_boundary,
    select_native_adjacent_boundary_steps,
)


def _registry(*step_ids: str) -> dict[str, object]:
    failure_behaviors = {
        "record_trade_decision": "continue_with_warning",
        "paper_portfolio": "decision_adjacent_block",
    }
    return {
        "steps": {
            step_id: {
                "status": "active",
                "allowed_to_affect_core_judgment": False,
                "failure_behavior": failure_behaviors[step_id],
                "execution": {"native_adjacent_boundary": "shadow_pilot"},
            }
            for step_id in step_ids
        }
    }


def _result(step_id: str, *, passed: bool = True) -> dict[str, object]:
    return {
        "status": "success" if passed else "error",
        "artifact_status": "PASS" if passed else "FAIL",
        "check_passed": passed,
        "writes_shadow_output": passed,
        "output_paths": [f"shadow/{step_id}.json"] if passed else [],
        "payload": {
            "risk_gate_status": "APPROVED_FOR_RESEARCH",
            "stance": "RISK_ON",
        },
    }


def test_live_registry_selects_only_adjacent_boundaries() -> None:
    assert NATIVE_ADJACENT_BOUNDARY_STEPS == {
        "record_trade_decision",
        "paper_portfolio",
    }
    selected = select_native_adjacent_boundary_steps(
        _registry("record_trade_decision", "paper_portfolio")
    )
    assert [item["step_id"] for item in selected] == [
        "paper_portfolio",
        "record_trade_decision",
    ]


def test_adjacent_pilot_is_stopped_and_respects_failure_behavior() -> None:
    assert native_adjacent_pilot_job in tuple(defs.jobs or ())
    assert native_adjacent_pilot_schedule in tuple(defs.schedules or ())
    assert native_adjacent_pilot_schedule.default_status.value == "STOPPED"
    assert len(NATIVE_ADJACENT_ASSETS) == 2
    assert len(NATIVE_ADJACENT_CHECKS) == 2
    blocking = {
        spec.name: spec.blocking
        for check in NATIVE_ADJACENT_CHECKS
        for spec in check.check_specs
    }
    assert blocking["native_adjacent_artifact_record_trade_decision"] is False
    assert blocking["native_adjacent_artifact_paper_portfolio"] is True


def test_adjacent_payload_is_shadow_only() -> None:
    payload = native_adjacent_payload(
        _result("paper_portfolio"),
        step_id="paper_portfolio",
        failure_behavior="decision_adjacent_block",
    )
    assert payload["authority"] == "shadow_only"
    assert payload["promotion_allowed"] is False
    assert payload["writes_legacy_output"] is False
    assert payload["writes_active_generation"] is False


def test_adjacent_pilot_materializes_with_external_upstream_keys() -> None:
    assets = build_native_adjacent_assets(
        document=_registry("record_trade_decision", "paper_portfolio"),
        boundary_runner=lambda step_id: _result(step_id),
    )
    checks = build_native_adjacent_checks(assets)

    result = materialize([*assets, *checks])

    assert result.success
    assert (
        result.output_for_node("native_adjacent_pilot__paper_portfolio")["check_passed"]
        is True
    )


def test_paper_failure_is_a_blocking_adjacent_check() -> None:
    assets = build_native_adjacent_assets(
        document=_registry("paper_portfolio"),
        boundary_runner=lambda _step_id: _result("paper_portfolio", passed=False),
    )
    checks = build_native_adjacent_checks(assets)

    with pytest.raises(
        DagsterAssetCheckFailedError, match="blocking asset check.*failed"
    ):
        materialize([*assets, *checks])


def test_record_boundary_writes_only_shadow_generation(tmp_path: Path) -> None:
    registry_path = tmp_path / "governance" / "daily_pipeline_registry.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        yaml.safe_dump(_registry("record_trade_decision"), sort_keys=False),
        encoding="utf-8",
    )
    decision_shadow = (
        tmp_path / "Output" / "state" / "health" / "native_decision_shadow" / "trade_decision"
    )
    decision_shadow.mkdir(parents=True)
    (decision_shadow / "latest.json").write_text(
        json.dumps(
            {
                "schema_version": "trade_decision.v3",
                "date": "2026-08-25",
                "decision": "WATCH",
                "stance": "WATCH",
                "size": 0.0,
                "effective_size": 0.0,
                "confidence": "low",
                "evidence_grade": "D",
                "allowed_size": "zero",
                "time_horizon": "1d",
                "asset_scope": [],
                "invalidation": ["freshness"],
                "paper_sources": [],
                "system_sources": [{"source": "judgment", "status": "WATCH"}],
                "trade_thesis": {"hypothesis": "watch"},
            }
        ),
        encoding="utf-8",
    )
    (decision_shadow / "risk_gate.json").write_text(
        json.dumps(
            {
                "risk_check": {
                    "status": "APPROVED_FOR_RESEARCH",
                    "risk_level": "LOW",
                }
            }
        ),
        encoding="utf-8",
    )

    result = execute_native_adjacent_boundary("record_trade_decision", root=tmp_path)

    assert result["status"] == "success"
    assert result["writes_legacy_output"] is False
    assert any(
        "native_adjacent_shadow/generation/trade_ledger" in path
        for path in result["output_paths"]
    )
    assert not (tmp_path / "Output" / "trade_ledger").exists()
