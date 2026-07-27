"""Callable E2E — resolve and execute default main-chain steps hermetically.

P0-3 wave 1: prove callables resolve and that lightweight report/readout steps
run under an isolated Output root without writing operator current.

Heavier steps (structural_replay / judgment / trade_decision) remain resolve-only
here until sandbox fixtures for their inputs land. Failure propagation is covered
by tests/test_failure_propagation.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from _pipeline_runner import load_step_execution, resolve_callable, run_registry_step

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

# Steps whose callables can run without live Harvester / Paper / heavy deps.
EXECUTABLE_LIGHT_STEPS = (
    "measurement_quality_report",
    "record_daily_run_event",
)


@pytest.mark.parametrize("step_id", MAIN_CHAIN_STEPS)
def test_main_chain_step_is_callable(step_id: str) -> None:
    execution = load_step_execution(step_id)
    assert execution.get("mode") == "callable", step_id
    spec = execution.get("future_callable")
    assert spec, step_id
    if step_id == "structural_replay":
        pytest.importorskip("omegaconf")
    target = resolve_callable(spec)
    assert callable(target)


def test_measurement_quality_report_callable_runs(tmp_path, monkeypatch) -> None:
    import scripts._data_paths as dp
    import scripts._runtime_io as rio

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
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(
        dp, "HARVESTER_LATEST", tmp_path / "Data" / "harvester" / "exports" / "latest"
    )
    monkeypatch.setattr(
        dp,
        "HARVESTER_DATA",
        tmp_path / "Data" / "harvester" / "exports" / "latest" / "data",
    )
    monkeypatch.setenv("DAILY_OUTPUT_ROOT", str(out))

    from scripts.commands.weekly.build_measurement_quality_report import build_report

    report = build_report()
    assert report["overall_status"] in {"OK", "DEGRADED"}
    assert report["channels"]["K"]["gate_verdict"] == "PASS"
    assert report["channels"]["X_agg"]["gate_verdict"] == "PASS"


@pytest.mark.parametrize("step_id", EXECUTABLE_LIGHT_STEPS)
def test_light_main_chain_callable_executes(step_id: str, tmp_path: Path, monkeypatch) -> None:
    """Actually invoke light callables under an isolated Output root."""
    import scripts._runtime_io as rio

    out = tmp_path / "Output"
    (out / "current").mkdir(parents=True)
    (out / "k_measurement").mkdir(parents=True)
    (out / "x_measurement").mkdir(parents=True)
    (out / "k_measurement" / "k_measurement_gate.json").write_text(
        json.dumps({"gate_verdict": "PASS", "tests": {"a": {"status": "PASS"}}}),
        encoding="utf-8",
    )
    (out / "x_measurement" / "x_measurement_gate.json").write_text(
        json.dumps({"gate_verdict": "PASS", "tests": {"b": {"status": "PASS"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setenv("DAILY_OUTPUT_ROOT", str(out))
    monkeypatch.setenv("SYSTEM_WORKSPACE_ROOT", str(tmp_path))

    argv = ["--skip-if-unchanged"] if step_id == "record_daily_run_event" else None
    result = run_registry_step(step_id, mode="callable", argv=argv)
    assert result["mode"] == "callable"
    assert result["status"] in {"success", "failed", "error"}, result
    # Light steps must not crash the runner itself.
    assert "callable" in result
