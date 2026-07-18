"""Callable E2E smoke — resolve main-chain pipeline steps without subprocess."""
from __future__ import annotations

import pytest
from _pipeline_runner import load_step_execution, resolve_callable

MAIN_CHAIN_STEPS = (
    "etf_refresh",
    "structural_replay",
    "k_measurement_gate",
    "x_measurement_gate",
    "measurement_quality_report",
    "judgment_layer",
    "judgment_promotion_gate",
    "trade_decision",
    "readme_first",
    "next_actions",
    "freshness_validator",
    "build_artifact_registry",
    "record_daily_run_event",
    "evidence_grade_report",
)


@pytest.mark.parametrize("step_id", MAIN_CHAIN_STEPS)
def test_main_chain_step_is_callable(step_id: str) -> None:
    execution = load_step_execution(step_id)
    assert execution.get("mode") == "callable", step_id
    spec = execution.get("future_callable")
    assert spec, step_id
    target = resolve_callable(spec)
    assert callable(target)


def test_measurement_quality_report_callable_runs(tmp_path, monkeypatch) -> None:
    import json

    import _runtime_io as rio

    out = tmp_path / "Output"
    (out / "k_measurement").mkdir(parents=True)
    (out / "x_measurement").mkdir(parents=True)
    (out / "current").mkdir(parents=True)
    (out / "k_measurement" / "k_measurement_gate.json").write_text(
        json.dumps({"gate_verdict": "PASS", "tests": {"a": {"status": "PASS"}}}),
        encoding="utf-8",
    )
    (out / "x_measurement" / "x_measurement_gate.json").write_text(
        json.dumps({"gate_verdict": "PASS", "tests": {"b": {"status": "PASS"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(rio, "ROOT", tmp_path)
    import _data_paths as dp

    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "HARVESTER_LATEST", tmp_path / "Data" / "harvester" / "exports" / "latest")
    monkeypatch.setattr(dp, "HARVESTER_DATA", tmp_path / "Data" / "harvester" / "exports" / "latest" / "data")
    monkeypatch.setenv("DAILY_OUTPUT_ROOT", str(out))

    from scripts.commands.weekly.build_measurement_quality_report import build_report

    report = build_report()
    assert report["overall_status"] in {"OK", "DEGRADED"}
    assert report["channels"]["K"]["gate_verdict"] == "PASS"
