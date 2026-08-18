"""Hermetic Dagster op smoke test — stubs step execution."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from dagster import build_op_context
from orchestration.ops.registry_step import execute_registry_sequence_op
from orchestration.runner import use_legacy_daily_run


def test_legacy_flag_default_off(monkeypatch):
    monkeypatch.delenv("SYSTEM_USE_LEGACY_DAILY_RUN", raising=False)
    assert use_legacy_daily_run() is False
    monkeypatch.setenv("SYSTEM_USE_LEGACY_DAILY_RUN", "1")
    assert use_legacy_daily_run() is True


def test_execute_registry_sequence_op_with_stubbed_steps(monkeypatch):
    executed: list[str] = []

    def fake_sequence(ctx, *, plan=None):
        executed.append(ctx.run_id)
        result = {"step": "stub", "status": "success", "duration_s": 0}
        ctx.record_fn(result)
        return [result]

    monkeypatch.setattr(
        "orchestration.ops.registry_step.execute_daily_sequence",
        fake_sequence,
    )
    recorded: list[dict] = []
    payload = {
        "args": SimpleNamespace(skip_harvester=True, skip_etf=True, force_weekly=False),
        "start_time": datetime.now(UTC),
        "total_steps": 1,
        "run_step_fn": lambda *a, **k: {"step": "x", "status": "success", "duration_s": 0},
        "record_fn": lambda result, input_artifacts=None: recorded.append(result),
        "benchmark_panel_path": Path("."),
        "run_id": "dagster_hermetic",
    }
    out = execute_registry_sequence_op(build_op_context(), payload)
    assert out["run_id"] == "dagster_hermetic"
    assert len(out["plan_digest"]) == 64
    assert executed == ["dagster_hermetic"]
    assert recorded and recorded[0]["step"] == "stub"
