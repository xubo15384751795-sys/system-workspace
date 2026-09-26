"""Step 2 contracts for the scheduler-to-publication execution spine."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scheduled_shells_are_process_adapters_only() -> None:
    scheduled = (ROOT / "scripts/run_daily_scheduled.sh").read_text(encoding="utf-8")
    dagster = (ROOT / "scripts/run_dagster_daily.sh").read_text(encoding="utf-8")
    orchestrate = (ROOT / "scripts/orchestrate.sh").read_text(encoding="utf-8")

    assert "retry_attempts" not in scheduled
    assert "sleep " not in scheduled
    assert "reconcile_generation.py" not in scheduled
    assert "scripts/daily_run.py" not in scheduled
    assert "execute_in_process" not in scheduled + dagster + orchestrate
    assert "reconcile_generation.py" not in orchestrate
    assert "scripts/daily_run.py" not in orchestrate
    assert "-m verity.cli daily" in dagster
    assert "-m verity.cli daily" in orchestrate


def test_default_cli_does_not_execute_the_legacy_outer_dagster_job() -> None:
    cli = (ROOT / "packages/orchestration/orchestration/cli.py").read_text(encoding="utf-8")
    daily_pipeline = (
        ROOT / "packages/orchestration/orchestration/daily_pipeline.py"
    ).read_text(encoding="utf-8")

    assert "daily_job.execute_in_process" not in cli
    assert "definitions import daily_job" not in cli
    assert "SYSTEM_INSIDE_DAGSTER_DAILY_JOB" not in daily_pipeline


def test_only_generated_plan_runner_owns_default_execute_boundary() -> None:
    runner = (ROOT / "packages/orchestration/orchestration/runner.py").read_text(
        encoding="utf-8"
    )
    definitions = (ROOT / "packages/orchestration/orchestration/definitions.py").read_text(
        encoding="utf-8"
    )

    assert runner.count("execute_in_process()") == 1
    assert "nested Dagster execution is forbidden" in runner
    assert "daily_job_entry" in definitions
    assert "nested_dagster_execution_forbidden" in definitions


def test_daily_run_binds_runtime_plan_to_the_run_bundle_and_payload() -> None:
    source = (ROOT / "verity/cli/daily_run.py").read_text(encoding="utf-8")
    assert "compile_runtime_plan" in source
    assert "compiled_runtime_plan.write(bundle.run_dir / \"compiled_runtime_plan.json\")" in source
    assert "run_step_fn=_run_compiled_step" in source
    assert "compiled_plan=compiled_plan" in source
    assert "runtime_plan=compiled_runtime_plan" in source
