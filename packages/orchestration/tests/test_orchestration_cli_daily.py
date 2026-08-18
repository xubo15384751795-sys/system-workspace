"""CLI smoke: Dagster daily_job dry-run succeeds."""
from __future__ import annotations

import os

from orchestration.cli import cmd_daily
from system_runtime.run_outcome import EXIT_EXECUTION_FAILURE, EXIT_MANDATORY_SINK_FAILURE, RunOutcome


def test_cmd_daily_dry_run():
    assert cmd_daily(["--dry-run"]) == 0


def test_cmd_daily_returns_typed_failure_code_when_dagster_step_fails(monkeypatch):
    outcome = RunOutcome(
        run_id="failed-dagster-run",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
        reason_codes=["ADMISSION_REJECTED"],
    )

    def fake_run(_argv):
        os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(outcome.exit_code)
        return outcome

    monkeypatch.setattr("orchestration.daily_pipeline.run_scheduled_daily", fake_run)
    assert cmd_daily(["--dry-run"]) == outcome.exit_code


def test_cmd_daily_returns_mandatory_sink_failure_after_outcome(monkeypatch):
    class FailingJob:
        def execute_in_process(self):
            os.environ["SYSTEM_DAILY_OUTCOME_READY"] = "1"
            os.environ["SYSTEM_DAILY_SINKS_COMPLETE"] = "0"
            os.environ["SYSTEM_DAILY_EXIT_CODE"] = "0"
            raise RuntimeError("learning hub sink failed")

    monkeypatch.setattr("orchestration.definitions.daily_job", FailingJob())

    assert cmd_daily(["--dry-run"]) == EXIT_MANDATORY_SINK_FAILURE


def test_cmd_daily_materializes_early_failure_before_wrapper(monkeypatch, tmp_path):
    class FailingJob:
        def execute_in_process(self):
            raise RuntimeError("fixture-only dagster bootstrap failure")

    monkeypatch.setattr("orchestration.definitions.daily_job", FailingJob())

    assert cmd_daily(["--output-root", str(tmp_path / "Output")]) == EXIT_EXECUTION_FAILURE
