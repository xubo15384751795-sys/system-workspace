from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from dagster import RetryPolicy, materialize

from orchestration.native_daily import (
    NATIVE_CORE_BOUNDARY_ENV,
    build_native_daily_assets,
    run_daily_sequence_via_native_assets,
    use_native_core_boundaries,
    use_native_daily_assets,
)
from orchestration.native_daily_checks import build_native_daily_checks
from orchestration.assets import native_batch
from workbench.surfaces import (
    build_artifact_registry,
    build_change_analysis,
    build_evidence_grade_report,
)
from workbench.measurement import build_measurement_quality_report
from orchestration.runner import (
    DailyRunPayload,
    run_daily_sequence_direct,
    run_daily_sequence_via_dagster,
)
from verity.runtime.runtime_io import ROOT
from orchestration.definitions import (
    defs,
    native_daily_shadow_job,
    native_daily_shadow_schedule,
    native_pilot_job,
    native_pilot_schedule,
)
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import CompiledPipeline, CompiledStep, load_pipeline


def _step(step_id: str, *, failure_behavior: str = "continue_with_warning") -> CompiledStep:
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
        outputs=(),
        failure_behavior=failure_behavior,
        affects_core_judgment=False,
    )


def _plan(*, harvester_behavior: str = "continue_with_warning") -> CompiledPipeline:
    return CompiledPipeline(
        schema_version="native-daily-test.v1",
        steps=(
            _step("harvester", failure_behavior=harvester_behavior),
            _step("judgment", failure_behavior="block_current_readout"),
            _step("trade"),
        ),
        external_inputs=(),
        edges={"judgment": ("harvester",), "trade": ("judgment",)},
        profiles={"daily": ("harvester", "judgment", "trade")},
    )


def _payload(plan: CompiledPipeline, recorded: list[dict]) -> DailyRunPayload:
    return DailyRunPayload(
        args=SimpleNamespace(skip_harvester=False, skip_etf=False, force_weekly=True),
        start_time=datetime(2026, 8, 25, tzinfo=UTC),
        total_steps=len(plan.sequence()),
        run_step_fn=lambda *args, **kwargs: {
            "step": args[0],
            "status": "success",
            "duration_s": 0,
        },
        record_fn=lambda result, input_artifacts=None: recorded.append(result),
        benchmark_panel_path=Path("."),
        run_id="native-daily-test",
        plan=plan,
    )


def test_native_daily_flag_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("SYSTEM_USE_NATIVE_DAILY_ASSETS", raising=False)
    assert use_native_daily_assets() is False
    monkeypatch.setenv("SYSTEM_USE_NATIVE_DAILY_ASSETS", "1")
    assert use_native_daily_assets() is True


def test_native_core_boundary_flag_is_separate_and_opt_in(monkeypatch) -> None:
    monkeypatch.delenv(NATIVE_CORE_BOUNDARY_ENV, raising=False)
    assert use_native_core_boundaries() is False
    monkeypatch.setenv(NATIVE_CORE_BOUNDARY_ENV, "1")
    assert use_native_core_boundaries() is True


def test_native_daily_uses_core_boundary_only_with_core_flag(monkeypatch) -> None:
    plan = CompiledPipeline(
        schema_version="native-core-boundary-test.v1",
        steps=(_step("neutral_pressure_measurement", failure_behavior="block_current_readout"),),
        external_inputs=(),
        edges={},
        profiles={"daily": ("neutral_pressure_measurement",)},
    )
    recorded: list[dict] = []
    monkeypatch.setenv(NATIVE_CORE_BOUNDARY_ENV, "1")
    monkeypatch.setattr(
        "orchestration.native_daily.execute_native_core_boundary",
        lambda step_id, **_kwargs: {
            "step": step_id,
            "status": "success",
            "mode": "native_core_boundary",
            "duration_s": 0,
            "authority": "shadow_only",
            "promotion_allowed": False,
            "writes_legacy_output": False,
        },
    )

    asset = build_native_daily_assets(_payload(plan, recorded), plan=plan)[0]
    metadata = asset.metadata_by_key[asset.key]
    result = materialize([asset])

    assert result.success
    assert metadata["core_boundary"] is True
    assert metadata["file_boundary"] is False
    assert metadata["writes_legacy_output"] is False
    assert recorded[0]["mode"] == "native_core_boundary"


def test_runner_dispatches_native_graph_only_with_opt_in_flag(monkeypatch) -> None:
    plan = _plan()
    payload = _payload(plan, [])
    expected = [{"step": "native_probe", "status": "success"}]
    monkeypatch.setenv("SYSTEM_USE_NATIVE_DAILY_ASSETS", "1")
    monkeypatch.setattr(
        "orchestration.native_daily.run_daily_sequence_via_native_assets",
        lambda _payload: expected,
    )

    assert run_daily_sequence_via_dagster(payload) == expected


def test_native_pilot_job_and_schedule_are_registered_but_stopped() -> None:
    assert native_pilot_job in tuple(defs.jobs or ())
    assert native_pilot_schedule in tuple(defs.schedules or ())
    assert native_pilot_schedule.default_status.value == "STOPPED"
    assert native_pilot_job.description.startswith("Stopped Wave 4")


def test_full_native_daily_shadow_job_is_registered_but_stopped() -> None:
    assert native_daily_shadow_job in tuple(defs.jobs or ())
    assert native_daily_shadow_schedule in tuple(defs.schedules or ())
    assert native_daily_shadow_schedule.default_status.value == "STOPPED"
    assert "CompiledPlan" in native_daily_shadow_job.description


def test_full_native_daily_shadow_job_materializes_real_plan_without_business_execution() -> None:
    plan = load_pipeline(WorkspacePaths(root=ROOT))
    result = defs.resolve_job_def("native_daily_shadow_job").execute_in_process()

    materializations = [
        event for event in result.all_events if event.event_type_value == "ASSET_MATERIALIZATION"
    ]
    assert result.success
    assert len(materializations) == len(plan.sequence())


def test_native_pilot_job_materializes_registered_assets_without_legacy_writes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(native_batch, "build_data_gaps", lambda: {"fixture": "data_gaps"})
    monkeypatch.setattr(
        build_artifact_registry,
        "build_artifact_registry",
        lambda: {"fixture": "artifact_registry"},
    )
    monkeypatch.setattr(
        build_change_analysis,
        "build_change_analysis",
        lambda: {"fixture": "change_analysis"},
    )
    monkeypatch.setattr(
        build_evidence_grade_report,
        "build_evidence_grade_report",
        lambda: {"fixture": "evidence_grade"},
    )
    monkeypatch.setattr(
        build_measurement_quality_report,
        "build_report",
        lambda: {"overall_status": "OK", "fixture": "measurement_quality"},
    )

    result = defs.resolve_job_def("native_pilot_job").execute_in_process()

    materializations = [
        event for event in result.all_events if event.event_type_value == "ASSET_MATERIALIZATION"
    ]
    assert result.success
    assert len(materializations) == 5


def test_native_daily_compiles_sequence_barrier_and_semantic_edges() -> None:
    plan = _plan()
    assets = build_native_daily_assets(_payload(plan, []), plan=plan)

    assert [asset.key.path for asset in assets] == [
        ["native_daily", "daily_step_001_harvester"],
        ["native_daily", "daily_step_002_judgment"],
        ["native_daily", "daily_step_003_trade"],
    ]
    assert all(asset.op.retry_policy.max_retries == 1 for asset in assets)
    judgment_metadata = assets[1].metadata_by_key[assets[1].key]
    assert judgment_metadata["upstream_steps"] == ["harvester"]
    assert judgment_metadata["execution_upstream_steps"] == ["harvester"]
    assert judgment_metadata["authority"] == "shadow_only"


def test_native_daily_shadow_checks_cover_every_asset_and_are_nonblocking() -> None:
    assets = build_native_daily_assets(_payload(_plan(), []), plan=_plan())
    checks = build_native_daily_checks(assets)
    blocking_checks = build_native_daily_checks(assets, blocking=True)

    assert len(checks) == len(assets) == 3
    assert all(not spec.blocking for check in checks for spec in check.check_specs)
    assert all(spec.blocking for check in blocking_checks for spec in check.check_specs)


def test_native_daily_shadow_checks_materialize_success_results() -> None:
    recorded: list[dict] = []
    plan = _plan()
    assets = build_native_daily_assets(_payload(plan, recorded), plan=plan)
    checks = build_native_daily_checks(assets)

    result = materialize([*assets, *checks])

    evaluations = [
        event
        for event in result.all_events
        if event.event_type_value == "ASSET_CHECK_EVALUATION"
    ]
    assert result.success
    assert len(evaluations) == 3
    assert all(getattr(event.event_specific_data, "passed", False) for event in evaluations)


def test_native_daily_blocking_check_prevents_downstream_materialization(monkeypatch) -> None:
    plan = _plan()
    attempts: list[str] = []
    monkeypatch.setattr(
        "orchestration.native_daily.NATIVE_DAILY_RETRY_POLICY",
        RetryPolicy(max_retries=0, delay=0),
    )

    def failing_upstream(step_id, _context, *, plan=None):
        attempts.append(step_id)
        if step_id == "harvester":
            return {"step": step_id, "status": "failed", "duration_s": 0}
        return {"step": step_id, "status": "success", "duration_s": 0}

    monkeypatch.setattr("orchestration.native_daily.execute_step", failing_upstream)
    assets = build_native_daily_assets(_payload(plan, []), plan=plan)
    checks = build_native_daily_checks(assets, blocking=True)

    result = materialize([*assets, *checks], raise_on_error=False)

    materialized_steps = {
        event.asset_key.path[-1]
        for event in result.all_events
        if event.event_type_value == "ASSET_MATERIALIZATION" and event.asset_key
    }
    assert attempts == ["harvester"]
    assert "daily_step_001_harvester" in materialized_steps
    assert "daily_step_002_judgment" not in materialized_steps
    assert "daily_step_003_trade" not in materialized_steps


def test_native_daily_matches_direct_executor_for_success(monkeypatch) -> None:
    plan = _plan()
    native_recorded: list[dict] = []
    direct_recorded: list[dict] = []

    def fake_execute(step_id, context, *, plan=None):
        return {"step": step_id, "status": "success", "duration_s": 0}

    monkeypatch.setattr("orchestration.native_daily.execute_step", fake_execute)
    monkeypatch.setattr("orchestration.sequence_executor.execute_step", fake_execute)

    native_results = run_daily_sequence_via_native_assets(_payload(plan, native_recorded))
    direct_results = run_daily_sequence_direct(_payload(plan, direct_recorded))

    assert native_results == direct_results
    assert native_recorded == direct_recorded == native_results


def test_native_daily_preserves_blocked_upstream_semantics(monkeypatch) -> None:
    plan = _plan(harvester_behavior="block_current_readout")
    recorded: list[dict] = []
    monkeypatch.setattr(
        "orchestration.native_daily.NATIVE_DAILY_RETRY_POLICY",
        RetryPolicy(max_retries=1, delay=0),
    )

    def fake_execute(step_id, context, *, plan=None):
        return {"step": step_id, "status": "failed", "duration_s": 0}

    monkeypatch.setattr("orchestration.native_daily.execute_step", fake_execute)
    results = run_daily_sequence_via_native_assets(_payload(plan, recorded))

    assert [result["status"] for result in results] == [
        "failed",
        "blocked_upstream",
        "blocked_upstream",
    ]
    assert results[1]["blocked_by"] == ["harvester"]
    assert results[2]["blocked_by"] == ["judgment"]
    assert recorded == results


def test_native_daily_retries_runner_failure_result(monkeypatch) -> None:
    plan = _plan()
    recorded: list[dict] = []
    attempts: dict[str, int] = {}
    monkeypatch.setattr(
        "orchestration.native_daily.NATIVE_DAILY_RETRY_POLICY",
        RetryPolicy(max_retries=1, delay=0),
    )

    def flaky_result(step_id, _context, *, plan=None):
        attempts[step_id] = attempts.get(step_id, 0) + 1
        if step_id == "harvester" and attempts[step_id] == 1:
            return {
                "step": step_id,
                "status": "failed",
                "returncode": 1,
                "duration_s": 0,
            }
        return {"step": step_id, "status": "success", "duration_s": 0}

    monkeypatch.setattr("orchestration.native_daily.execute_step", flaky_result)

    results = run_daily_sequence_via_native_assets(_payload(plan, recorded))

    assert attempts["harvester"] == 2
    assert [result["status"] for result in results] == [
        "success",
        "success",
        "success",
    ]
    assert recorded == results


def test_native_and_generated_graphs_match_on_authoritative_plan_without_business_writes(
    monkeypatch,
) -> None:
    """Exercise the real registry sequence while keeping the step bodies hermetic."""
    plan = load_pipeline(WorkspacePaths(root=ROOT))
    native_recorded: list[dict] = []
    generated_recorded: list[dict] = []

    def fake_execute(step_id, _context, *, plan=None):
        return {
            "step": step_id,
            "status": "success",
            "duration_s": 0,
            "plan_digest": plan.plan_digest if plan is not None else "",
        }

    monkeypatch.delenv("SYSTEM_USE_NATIVE_DAILY_ASSETS", raising=False)
    monkeypatch.setattr("orchestration.native_daily.execute_step", fake_execute)
    monkeypatch.setattr("orchestration.runner.execute_step", fake_execute)

    native_results = run_daily_sequence_via_native_assets(
        _payload_for_plan(plan, native_recorded)
    )
    generated_results = run_daily_sequence_via_dagster(
        _payload_for_plan(plan, generated_recorded)
    )

    expected_steps = [str(item["id"]) for item in plan.sequence()]
    assert len(expected_steps) >= 20
    assert [item["step"] for item in native_results] == expected_steps
    assert [item["step"] for item in generated_results] == expected_steps
    assert [item["status"] for item in native_results] == [
        item["status"] for item in generated_results
    ]
    assert native_recorded == native_results
    assert generated_recorded == generated_results


def test_native_daily_retries_a_transient_asset_failure(monkeypatch) -> None:
    plan = _plan()
    recorded: list[dict] = []
    attempts: dict[str, int] = {}
    monkeypatch.setattr(
        "orchestration.native_daily.NATIVE_DAILY_RETRY_POLICY",
        RetryPolicy(max_retries=1, delay=0),
    )

    def flaky_execute(step_id, _context, *, plan=None):
        attempts[step_id] = attempts.get(step_id, 0) + 1
        if step_id == "harvester" and attempts[step_id] == 1:
            raise RuntimeError("transient fixture failure")
        return {"step": step_id, "status": "success", "duration_s": 0}

    monkeypatch.setattr("orchestration.native_daily.execute_step", flaky_execute)

    results = run_daily_sequence_via_native_assets(_payload(plan, recorded))

    assert attempts["harvester"] == 2
    assert [result["status"] for result in results] == [
        "success",
        "success",
        "success",
    ]


def _payload_for_plan(plan: CompiledPipeline, recorded: list[dict]) -> DailyRunPayload:
    return DailyRunPayload(
        args=SimpleNamespace(
            skip_harvester=False,
            skip_etf=False,
            force_weekly=True,
        ),
        start_time=datetime(2026, 8, 25, tzinfo=UTC),
        total_steps=len(plan.sequence()),
        run_step_fn=lambda *args, **kwargs: {
            "step": args[0],
            "status": "success",
            "duration_s": 0,
        },
        record_fn=lambda result, input_artifacts=None: recorded.append(result),
        benchmark_panel_path=Path("."),
        run_id="native-daily-authoritative-plan-test",
        plan=plan,
    )
