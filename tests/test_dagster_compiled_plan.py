"""Contract tests for the per-step Dagster graph generated from CompiledPlan."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from orchestration.runner import (
    DailyRunPayload,
    build_daily_step_job,
    run_daily_sequence_direct,
    run_daily_sequence_via_dagster,
)
from orchestration.shadow_parity import compare_sequence_results

from system_runtime.pipeline import CompiledPipeline, CompiledStep


def _step(
    step_id: str,
    *,
    failure_behavior: str = "continue_with_warning",
    outputs: tuple[str, ...] = (),
) -> CompiledStep:
    return CompiledStep(
        step_id=step_id,
        order=float(len(step_id)),
        status="active",
        owner="test",
        schedule="daily",
        command="python -c pass",
        callable_spec="",
        execution_mode="subprocess",
        inputs=(),
        outputs=outputs,
        failure_behavior=failure_behavior,
        affects_core_judgment=False,
    )


def _plan(
    *,
    harvester_behavior: str,
    judgment_behavior: str,
    outputs_by_step: dict[str, tuple[str, ...]] | None = None,
) -> CompiledPipeline:
    outputs_by_step = outputs_by_step or {}
    steps = (
        _step(
            "harvester",
            failure_behavior=harvester_behavior,
            outputs=outputs_by_step.get("harvester", ()),
        ),
        _step(
            "judgment",
            failure_behavior=judgment_behavior,
            outputs=outputs_by_step.get("judgment", ()),
        ),
        _step("trade", outputs=outputs_by_step.get("trade", ())),
    )
    return CompiledPipeline(
        schema_version="test.v1",
        steps=steps,
        external_inputs=(),
        edges={"judgment": ("harvester",), "trade": ("judgment",)},
        profiles={"daily": ("harvester", "judgment", "trade")},
    )


def _payload(plan: CompiledPipeline, recorded: list[dict]) -> DailyRunPayload:
    return DailyRunPayload(
        args=SimpleNamespace(skip_harvester=False, skip_etf=False, force_weekly=True),
        start_time=datetime(2026, 8, 10, tzinfo=UTC),
        total_steps=len(plan.sequence()),
        run_step_fn=lambda *args, **kwargs: {
            "step": args[0],
            "status": "success",
            "duration_s": 0,
        },
        record_fn=lambda result, input_artifacts=None: recorded.append(result),
        benchmark_panel_path=Path("."),
        run_id="dagster-compiled-plan-test",
        plan=plan,
    )


def test_graph_has_one_step_op_per_compiled_step_plus_summary() -> None:
    plan = _plan(harvester_behavior="hold_flat", judgment_behavior="continue_with_warning")
    job = build_daily_step_job(_payload(plan, []), plan=plan)

    names = [node.name for node in job.graph.node_defs]
    assert names[:3] == [
        "daily_step_001_harvester",
        "daily_step_002_judgment",
        "daily_step_003_trade",
    ]
    assert names[-1] == "daily_compiled_plan_graph_summary"


def test_nested_dagster_execution_fails_closed(monkeypatch) -> None:
    plan = _plan(harvester_behavior="hold_flat", judgment_behavior="continue_with_warning")
    monkeypatch.setenv("SYSTEM_DAGSTER_EXECUTION_ACTIVE", "1")

    with pytest.raises(RuntimeError, match="nested Dagster execution is forbidden"):
        run_daily_sequence_via_dagster(_payload(plan, []))

    assert os.environ["SYSTEM_DAGSTER_EXECUTION_ACTIVE"] == "1"


def test_graph_emits_contract_metadata_for_each_compiled_step() -> None:
    plan = _plan(harvester_behavior="hold_flat", judgment_behavior="continue_with_warning")
    payload = _payload(plan, [])
    result = build_daily_step_job(payload, plan=plan).execute_in_process()

    metadata_by_step: dict[str, dict[str, object]] = {}
    for event in result.all_events:
        if event.event_type_value != "STEP_OUTPUT" or not event.step_key.startswith("daily_step_"):
            continue
        metadata = event.step_output_data.metadata
        step_id = metadata["step_id"].text
        metadata_by_step[step_id] = metadata

    assert set(metadata_by_step) == {step["id"] for step in plan.sequence()}
    for sequence_record in plan.sequence():
        step_id = str(sequence_record["id"])
        step = plan.step(step_id)
        metadata = metadata_by_step[step_id]
        assert metadata["owner"].text == step.owner
        assert metadata["plan_digest"].text == plan.plan_digest
        assert metadata["bundle_run_id"].text == payload.run_id
        assert metadata["failure_behavior"].text == step.failure_behavior
        assert metadata["inputs"].data == list(step.inputs)
        assert metadata["outputs"].data == list(step.outputs)
        assert metadata["upstream_steps"].data == list(plan.edges.get(step_id, ()))


def test_graph_propagates_blocking_failure_from_compiled_plan(monkeypatch) -> None:
    plan = _plan(
        harvester_behavior="block_current_readout",
        judgment_behavior="block_core_judgment",
    )
    recorded: list[dict] = []
    executed: list[str] = []

    def fake_execute(step_id, context, *, plan=None):
        executed.append(step_id)
        return {"step": step_id, "status": "failed", "duration_s": 0}

    monkeypatch.setattr("orchestration.runner.execute_step", fake_execute)
    results = run_daily_sequence_via_dagster(_payload(plan, recorded))

    assert [result["status"] for result in results] == [
        "failed",
        "blocked_upstream",
        "blocked_upstream",
    ]
    assert results[1]["blocked_by"] == ["harvester"]
    assert results[2]["blocked_by"] == ["judgment"]
    assert executed == ["harvester"]
    assert recorded == results


def test_graph_marks_downstream_success_as_degraded(monkeypatch) -> None:
    plan = _plan(
        harvester_behavior="hold_flat",
        judgment_behavior="continue_with_warning",
    )
    recorded: list[dict] = []

    def fake_execute(step_id, context, *, plan=None):
        status = "failed" if step_id == "harvester" else "success"
        return {"step": step_id, "status": status, "duration_s": 0}

    monkeypatch.setattr("orchestration.runner.execute_step", fake_execute)
    results = run_daily_sequence_via_dagster(_payload(plan, recorded))

    assert results[0]["status"] == "failed"
    assert results[1]["status"] == "success"
    assert results[1]["degraded"] is True
    assert results[1]["degraded_by"] == ["harvester"]
    assert results[2]["status"] == "success"


def test_graph_shadow_matches_direct_executor_for_same_plan(monkeypatch) -> None:
    plan = _plan(
        harvester_behavior="hold_flat",
        judgment_behavior="continue_with_warning",
    )

    received_plan_digests: list[str | None] = []

    def fake_execute(step_id, context, *, plan=None):
        resolved_plan = plan or context.plan
        received_plan_digests.append(resolved_plan.plan_digest if resolved_plan else None)
        return {"step": step_id, "status": "success", "duration_s": 0}

    monkeypatch.setattr("orchestration.runner.execute_step", fake_execute)
    monkeypatch.setattr("orchestration.sequence_executor.execute_step", fake_execute)

    graph_results = run_daily_sequence_via_dagster(_payload(plan, []))
    direct_results = run_daily_sequence_direct(_payload(plan, []))

    assert graph_results == direct_results
    assert received_plan_digests == [plan.plan_digest] * 6

    report = compare_sequence_results(
        direct_results,
        graph_results,
        plan_digest=plan.plan_digest,
    )
    assert report.execution_parity == "MATCH"
    # Current sequence results do not yet carry canonical lineage.  Keep this
    # explicit so execution parity cannot be mistaken for SYS-21 completion.
    assert report.canonical_lineage_parity == "NOT_PRESENT"
    assert report.status == "EXECUTION_MATCH_CANONICAL_UNAVAILABLE"
    assert report.promotion_allowed is False


def test_graph_shadow_matches_current_run_canonical_lineage(tmp_path, monkeypatch) -> None:
    """A stamped, validated output upgrades shadow status to lineage parity."""
    plan = _plan(
        harvester_behavior="hold_flat",
        judgment_behavior="continue_with_warning",
        outputs_by_step={"harvester": ("Output/current/neutral_pressure_snapshot.json",)},
    )
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(tmp_path))
    fixture = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "canonical_chain_parity.json").read_text(
            encoding="utf-8"
        )
    )
    run_id = "dagster-compiled-plan-test"

    def fake_execute(step_id, context, *, plan=None):
        if step_id == "harvester":
            (tmp_path / "neutral_pressure_snapshot.json").write_text(
                json.dumps({"run_id": run_id, "canonical_chain": fixture}),
                encoding="utf-8",
            )
        return {"step": step_id, "status": "success", "duration_s": 0}

    monkeypatch.setattr("orchestration.runner.execute_step", fake_execute)
    monkeypatch.setattr("orchestration.sequence_executor.execute_step", fake_execute)

    graph_results = run_daily_sequence_via_dagster(_payload(plan, []))
    direct_results = run_daily_sequence_direct(_payload(plan, []))
    report = compare_sequence_results(
        direct_results,
        graph_results,
        plan_digest=plan.plan_digest,
    )

    assert report.execution_parity == "MATCH"
    assert report.canonical_lineage_parity == "MATCH"
    assert report.status == "PASS"
    assert report.promotion_allowed is False


def test_graph_preserves_compiled_sequence_for_independent_steps(monkeypatch) -> None:
    """Shared output surfaces must not be rendered by an out-of-order op."""
    steps = (
        _step("first"),
        _step("second"),
        _step("third"),
    )
    plan = CompiledPipeline(
        schema_version="test.v1",
        steps=steps,
        external_inputs=(),
        edges={},
        profiles={"daily": ("first", "second", "third")},
    )
    executed: list[str] = []

    def fake_execute(step_id, context, *, plan=None):
        del context, plan
        executed.append(step_id)
        return {"step": step_id, "status": "success", "duration_s": 0}

    monkeypatch.setattr("orchestration.runner.execute_step", fake_execute)
    results = run_daily_sequence_via_dagster(_payload(plan, []))

    assert [result["step"] for result in results] == ["first", "second", "third"]
    assert executed == ["first", "second", "third"]
