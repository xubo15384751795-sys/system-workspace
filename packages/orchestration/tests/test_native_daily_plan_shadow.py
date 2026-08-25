from __future__ import annotations

import os
from pathlib import Path

from orchestration.native_daily import NATIVE_DAILY_ENV
from orchestration.operators.run_native_daily_plan_shadow import run_shadow
from system_runtime.pipeline import CompiledPipeline, CompiledStep


def _plan() -> CompiledPipeline:
    def step(step_id: str, order: float) -> CompiledStep:
        return CompiledStep(
            step_id=step_id,
            order=order,
            status="active",
            owner="test",
            schedule="daily",
            command="python -c pass",
            callable_spec="",
            execution_mode="subprocess",
            inputs=(),
            outputs=(),
            failure_behavior="continue_with_warning",
            affects_core_judgment=False,
        )

    return CompiledPipeline(
        schema_version="native-daily-shadow-test.v1",
        steps=(step("first", 1), step("second", 2)),
        external_inputs=(),
        edges={"second": ("first",)},
        profiles={"daily": ("first", "second")},
    )


def test_full_plan_shadow_matches_and_does_not_touch_current(
    tmp_path: Path,
    monkeypatch,
) -> None:
    current = tmp_path / "Output" / "current"
    current.mkdir(parents=True)
    sentinel = current / "sentinel.json"
    sentinel.write_text('{"unchanged": true}\n', encoding="utf-8")
    monkeypatch.setenv(NATIVE_DAILY_ENV, "1")

    report = run_shadow(root=tmp_path, plan=_plan())

    assert report["status"] == "MATCH"
    assert report["promotion_allowed"] is False
    assert report["execution_mode"] == "dry_run_no_business_execution"
    assert report["business_step_execution_attempted"] is False
    assert report["workspace_current_unchanged"] is True
    assert report["sequence_match"] is True
    assert report["result_match"] is True
    assert report["generated_job_node_count"] == 3  # two steps plus summary
    assert report["native_asset_check_count"] == 2
    assert report["native_asset_check_blocking"] is False
    assert os.environ[NATIVE_DAILY_ENV] == "1"
