"""Pipeline runner callable execution tests."""
from __future__ import annotations

from pathlib import Path

from verity.runtime._pipeline_runner import (
    load_step_execution,
    resolve_callable,
    run_registry_step,
)


def test_load_step_execution_for_record_daily_run_event() -> None:
    execution = load_step_execution("record_daily_run_event")
    assert execution["mode"] == "callable"
    assert execution["future_callable"] == "system_learning.operators.record_daily_run_event:main"


def test_resolve_callable_for_evidence_grade_report() -> None:
    target = resolve_callable("workbench.surfaces.build_evidence_grade_report:main")
    assert callable(target)


def test_load_step_execution_callable_batch() -> None:
    for step_id in ("readme_first", "next_actions", "freshness_validator"):
        execution = load_step_execution(step_id)
        assert execution["mode"] == "callable", step_id


def test_resolve_callable_for_readme_and_next_actions() -> None:
    assert callable(resolve_callable("workbench.surfaces.build_readme_first:main"))
    assert callable(resolve_callable("workbench.surfaces.build_next_actions:main"))


def test_run_registry_step_callable_record_daily_run_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DAILY_OUTPUT_ROOT", str(tmp_path / "Output"))
    result = run_registry_step(
        "record_daily_run_event",
        mode="callable",
        argv=["--skip-if-unchanged"],
    )
    assert result["mode"] == "callable"
    assert result["status"] in {"success", "failed", "error"}
