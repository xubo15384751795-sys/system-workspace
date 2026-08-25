from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from dagster import materialize
from dagster._core.errors import DagsterAssetCheckFailedError

from orchestration.assets.native_decision import (
    NATIVE_DECISION_ASSETS,
    NATIVE_DECISION_CHECKS,
    build_native_decision_assets,
    build_native_decision_checks,
    native_decision_payload,
)
from orchestration.definitions import (
    defs,
    native_decision_pilot_job,
    native_decision_pilot_schedule,
)
from orchestration.native_decision_boundaries import (
    NATIVE_DECISION_BOUNDARY_STEPS,
    execute_native_decision_boundary,
    select_native_decision_boundary_steps,
)


def _registry(*step_ids: str) -> dict[str, object]:
    failure_behaviors = {
        "judgment_layer": "block_current_readout",
        "judgment_promotion_gate": "block_promotion",
        "trade_decision": "hold_flat",
        "risk_gate": "hold_flat",
    }
    return {
        "steps": {
            step_id: {
                "status": "active",
                "allowed_to_affect_core_judgment": True,
                "failure_behavior": failure_behaviors[step_id],
                "execution": {"native_decision_boundary": "shadow_pilot"},
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
            "status": "BLOCKED" if step_id == "judgment_promotion_gate" else "WATCH"
        },
    }


def test_live_registry_selects_only_decision_boundaries() -> None:
    assert NATIVE_DECISION_BOUNDARY_STEPS == {
        "judgment_layer",
        "judgment_promotion_gate",
        "trade_decision",
        "risk_gate",
    }
    selected = select_native_decision_boundary_steps(
        _registry(
            "judgment_layer",
            "judgment_promotion_gate",
            "trade_decision",
            "risk_gate",
        )
    )
    assert [item["step_id"] for item in selected] == [
        "judgment_layer",
        "judgment_promotion_gate",
        "risk_gate",
        "trade_decision",
    ]


def test_decision_pilot_is_registered_stopped_with_blocking_checks() -> None:
    assert native_decision_pilot_job in tuple(defs.jobs or ())
    assert native_decision_pilot_schedule in tuple(defs.schedules or ())
    assert native_decision_pilot_schedule.default_status.value == "STOPPED"
    assert len(NATIVE_DECISION_ASSETS) == 4
    assert len(NATIVE_DECISION_CHECKS) == 4
    assert all(
        spec.blocking for check in NATIVE_DECISION_CHECKS for spec in check.check_specs
    )


def test_decision_payload_is_shadow_only() -> None:
    payload = native_decision_payload(
        _result("trade_decision"),
        step_id="trade_decision",
        failure_behavior="hold_flat",
    )
    assert payload["authority"] == "shadow_only"
    assert payload["promotion_allowed"] is False
    assert payload["writes_legacy_output"] is False
    assert payload["writes_active_generation"] is False
    assert payload["check_passed"] is True


def test_decision_pilot_materializes_dependencies_and_checks() -> None:
    assets = build_native_decision_assets(
        document=_registry(
            "judgment_layer",
            "judgment_promotion_gate",
            "trade_decision",
            "risk_gate",
        ),
        boundary_runner=lambda step_id: _result(step_id),
    )
    checks = build_native_decision_checks(assets)

    result = materialize([*assets, *checks])

    assert result.success
    assert (
        result.output_for_node("native_decision_pilot__risk_gate")["check_passed"]
        is True
    )


def test_decision_pilot_blocking_check_stops_downstream_assets() -> None:
    def runner(step_id: str) -> dict[str, object]:
        return _result(step_id, passed=step_id != "judgment_layer")

    assets = build_native_decision_assets(
        document=_registry(
            "judgment_layer",
            "judgment_promotion_gate",
            "trade_decision",
            "risk_gate",
        ),
        boundary_runner=runner,
    )
    checks = build_native_decision_checks(assets)

    with pytest.raises(
        DagsterAssetCheckFailedError, match="blocking asset check.*failed"
    ):
        materialize([*assets, *checks])


def test_risk_boundary_writes_only_shadow_root(tmp_path: Path) -> None:
    registry_path = tmp_path / "governance" / "daily_pipeline_registry.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        yaml.safe_dump(_registry("risk_gate"), sort_keys=False),
        encoding="utf-8",
    )
    shadow_root = tmp_path / "Output" / "health" / "shadow"
    decision_path = shadow_root / "trade_decision" / "latest.json"
    decision_path.parent.mkdir(parents=True)
    decision_path.write_text(
        json.dumps(
            {
                "schema_version": "trade_decision.v3",
                "date": "2026-08-25",
                "decision": "WATCH",
                "confidence": "low",
                "evidence_grade": "D",
            }
        ),
        encoding="utf-8",
    )

    result = execute_native_decision_boundary(
        "risk_gate",
        root=tmp_path,
        shadow_root=shadow_root,
    )

    assert result["status"] == "success"
    assert result["writes_legacy_output"] is False
    assert (shadow_root / "trade_decision" / "risk_gate.json").is_file()
    assert not (tmp_path / "Output" / "trade_decision").exists()
