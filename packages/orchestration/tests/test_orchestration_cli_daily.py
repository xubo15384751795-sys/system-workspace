"""CLI smoke: the scheduled adapter enters the single execution spine."""
from __future__ import annotations

import os

from orchestration.cli import cmd_daily
from system_runtime.context import RuntimeContext
from system_runtime.run_outcome import EXIT_EXECUTION_FAILURE, EXIT_MANDATORY_SINK_FAILURE, RunOutcome
from system_runtime.secrets import EnvironmentSecretProvider


def test_cmd_daily_dry_run():
    assert cmd_daily(["--dry-run"]) == 0


def test_cmd_daily_normalizes_fred_alias_at_context_boundary(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("OPENBB_FRED_API_KEY", "fixture-fred-key")
    context = RuntimeContext.discover(
        secrets=EnvironmentSecretProvider(aliases={"FRED_API_KEY": ("OPENBB_FRED_API_KEY",)})
    )
    outcome = RunOutcome(
        run_id="fred-secret-boundary",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="PASS",
        publish_status="COMMITTED",
        authority_mode="authoritative",
    )

    def fake_spine(argv, *, runtime_context=None):
        assert argv == ["--dry-run"]
        assert runtime_context is context
        return outcome

    monkeypatch.setattr("orchestration.daily_pipeline.run_scheduled_daily", fake_spine)
    assert cmd_daily(["--dry-run"], runtime_context=context) == 0
    assert os.environ["FRED_API_KEY"] == "fixture-fred-key"
    assert "OPENBB_FRED_API_KEY" not in os.environ


def test_cmd_daily_uses_python_spine_without_legacy_outer_job(monkeypatch):
    outcome = RunOutcome(
        run_id="single-spine",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="PASS",
        publish_status="PUBLISHED",
        authority_mode="authoritative",
    )
    called: list[list[str]] = []

    def fake_spine(argv):
        called.append(list(argv))
        return outcome

    class ForbiddenOuterJob:
        def execute_in_process(self):
            raise AssertionError("legacy outer daily_job must not be touched")

    monkeypatch.setattr("orchestration.daily_pipeline.run_scheduled_daily", fake_spine)
    monkeypatch.setattr("orchestration.definitions.daily_job", ForbiddenOuterJob())

    assert cmd_daily(["--dry-run"]) == outcome.exit_code
    assert called == [["--dry-run"]]


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
    def failing_spine(_argv):
        os.environ["SYSTEM_DAILY_OUTCOME_READY"] = "1"
        os.environ["SYSTEM_DAILY_SINKS_COMPLETE"] = "0"
        os.environ["SYSTEM_DAILY_EXIT_CODE"] = "0"
        raise RuntimeError("learning hub sink failed")

    monkeypatch.setattr("orchestration.daily_pipeline.run_scheduled_daily", failing_spine)

    assert cmd_daily(["--dry-run"]) == EXIT_MANDATORY_SINK_FAILURE


def test_cmd_daily_materializes_early_failure_before_wrapper(monkeypatch, tmp_path):
    def failing_spine(_argv):
        raise RuntimeError("fixture-only execution-spine bootstrap failure")

    monkeypatch.setattr("orchestration.daily_pipeline.run_scheduled_daily", failing_spine)

    assert cmd_daily(["--output-root", str(tmp_path / "Output")]) == EXIT_EXECUTION_FAILURE
