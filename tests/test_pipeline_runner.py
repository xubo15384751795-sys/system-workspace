"""Pipeline runner callable execution tests."""
from __future__ import annotations

from pathlib import Path

import _pipeline_runner
from _pipeline_runner import (
    load_step_execution,
    resolve_callable,
    run_callable_step,
    run_registry_step,
)


def test_load_step_execution_for_record_daily_run_event() -> None:
    execution = load_step_execution("record_daily_run_event")
    assert execution["mode"] == "callable"
    assert execution["future_callable"] == "scripts.record_daily_run_event:main"


def test_resolve_callable_for_evidence_grade_report() -> None:
    target = resolve_callable("scripts.commands.weekly.build_evidence_grade_report:main")
    assert callable(target)


def test_load_step_execution_callable_batch() -> None:
    for step_id in (
        "readme_first",
        "next_actions",
        "freshness_validator",
        "signal_card",
        "signal_consensus",
        "work_brief",
    ):
        execution = load_step_execution(step_id)
        assert execution["mode"] == "callable", step_id


def test_resolve_callable_for_readme_and_next_actions() -> None:
    assert callable(resolve_callable("scripts.commands.weekly.build_readme_first:main"))
    assert callable(resolve_callable("scripts.commands.weekly.build_next_actions:main"))


def test_resolve_callable_for_risk_gate_uses_live_entrypoint() -> None:
    assert callable(resolve_callable("scripts.trade_risk_gate:main"))


def test_callable_step_applies_and_restores_environment(monkeypatch) -> None:
    observed: dict[str, str | None] = {}

    def target() -> int:
        observed["during"] = __import__("os").environ.get("PIPELINE_RUNNER_TEST_ENV")
        return 0

    monkeypatch.setattr(_pipeline_runner, "resolve_callable", lambda _spec: target)
    monkeypatch.delenv("PIPELINE_RUNNER_TEST_ENV", raising=False)
    result = run_callable_step(
        "env_probe",
        "tests.env_probe:main",
        env={"PIPELINE_RUNNER_TEST_ENV": "callable"},
    )

    assert result["status"] == "success"
    assert observed["during"] == "callable"
    assert "PIPELINE_RUNNER_TEST_ENV" not in __import__("os").environ


def test_run_registry_step_callable_record_daily_run_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAILY_OUTPUT_ROOT", str(tmp_path / "Output"))
    result = run_registry_step(
        "record_daily_run_event",
        mode="callable",
        argv=["--skip-if-unchanged"],
    )
    assert result["mode"] == "callable"
    assert result["status"] in {"success", "failed", "error"}


def test_harvester_subprocess_has_bounded_timeout(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(*_args, **kwargs):
        observed["timeout"] = kwargs["timeout"]
        return _pipeline_runner.subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(_pipeline_runner.subprocess, "run", fake_run)
    result = _pipeline_runner.run_subprocess_step("harvester", ["python", "-c", "pass"])

    assert result["status"] == "success"
    assert observed["timeout"] == 900


def test_harvester_subprocess_preserves_domain_outcome(monkeypatch) -> None:
    payload = (
        '{"status":"market_closed","reason":"market_closed_reused_latest",'
        '"release_id":"2026-08-07-r2","session_date":"2026-08-07"}'
    )

    def fake_run(*_args, **kwargs):
        return _pipeline_runner.subprocess.CompletedProcess(
            args=[], returncode=0, stdout=payload, stderr=""
        )

    monkeypatch.setattr(_pipeline_runner.subprocess, "run", fake_run)
    result = _pipeline_runner.run_subprocess_step("harvester", ["python", "-c", "pass"])

    assert result["status"] == "success"
    assert result["release_status"] == "market_closed"
    assert result["release_reason"] == "market_closed_reused_latest"
    assert result["release_id"] == "2026-08-07-r2"
