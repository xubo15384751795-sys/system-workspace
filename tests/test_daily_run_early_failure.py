"""Regression tests for typed failures before normal RunOutcome creation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from system_runtime.run_outcome import (
    EXIT_EXECUTION_FAILURE,
    EXIT_MANDATORY_SINK_FAILURE,
)


def _payloads(path: Path) -> list[dict]:
    return [
        json.loads(line)["payload"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_direct_daily_run_early_failure_has_one_typed_identity(monkeypatch, tmp_path):
    from scripts import daily_run

    output_root = tmp_path / "Output"

    def fail_before_plan(_paths):
        raise RuntimeError("fixture-only initialization failure")

    monkeypatch.delenv("SYSTEM_ORCHESTRATOR", raising=False)
    monkeypatch.delenv("SYSTEM_INSIDE_DAGSTER_DAILY_JOB", raising=False)
    monkeypatch.setattr(daily_run, "load_pipeline", fail_before_plan)

    exit_code = daily_run.main(["--output-root", str(output_root), "--tag", "fixture"])

    assert exit_code == EXIT_EXECUTION_FAILURE
    alert = json.loads((output_root / "alerts" / "latest_alert.json").read_text(encoding="utf-8"))
    events = _payloads(output_root / "runtime_events" / next(
        path.name for path in (output_root / "runtime_events").iterdir()
    ))
    run_dirs = list((output_root / "runs").iterdir())
    assert len(run_dirs) == 1
    run_outcome = json.loads((run_dirs[0] / "run_outcome.json").read_text(encoding="utf-8"))

    assert alert["run_id"] == run_outcome["run_id"] == events[0]["run_id"]
    assert alert["outcome"] == run_outcome == events[0]["outcome"]
    assert run_outcome["status"] == "partial_failure"
    assert run_outcome["reason_codes"] == ["EARLY_RUN_FAILURE"]
    operator_events = events[0].get("operator_events", [])
    assert {event["event_type"] for event in operator_events} >= {
        "publish_verdict",
        "authority_denial",
    }
    assert all(event["run_id"] == run_outcome["run_id"] for event in operator_events)


def test_dagster_wrapper_returns_typed_early_failure(monkeypatch, tmp_path):
    from orchestration import daily_pipeline

    from scripts import daily_run

    output_root = tmp_path / "Output"

    def fail_before_run(_args):
        raise ValueError("fixture-only dagster boundary failure")

    monkeypatch.setattr(daily_run, "run_daily", fail_before_run)
    outcome = daily_pipeline.run_scheduled_daily(["--output-root", str(output_root)])

    assert outcome.exit_code == EXIT_EXECUTION_FAILURE
    assert outcome.reason_codes == ["EARLY_RUN_FAILURE"]
    assert outcome.status == "partial_failure"
    assert daily_pipeline.os.environ["SYSTEM_DAILY_EXIT_CODE"] == str(EXIT_EXECUTION_FAILURE)


def test_dagster_wrapper_preserves_late_mandatory_sink_failure(monkeypatch):
    from orchestration import daily_pipeline

    from scripts import daily_run

    def fail_after_outcome(_args):
        monkeypatch.setenv("SYSTEM_DAILY_OUTCOME_READY", "1")
        monkeypatch.setenv("SYSTEM_DAILY_SINKS_COMPLETE", "0")
        raise RuntimeError("fixture-only mandatory sink failure")

    monkeypatch.setattr(daily_run, "run_daily", fail_after_outcome)
    with pytest.raises(RuntimeError):
        daily_pipeline.run_scheduled_daily(["--dry-run"])

    assert daily_pipeline.os.environ["SYSTEM_DAILY_EXIT_CODE"] == str(
        EXIT_MANDATORY_SINK_FAILURE
    )
