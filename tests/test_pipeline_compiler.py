"""Acceptance tests for WP1B: single registry/compiler/executor authority.

Defines the contract that ``daily_pipeline_registry.yaml`` is the sole
execution authority, compiled by one ``Compiler`` into a ``CompiledPlan``
that the executor accepts.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

_REGISTRY = Path(__file__).resolve().parents[1] / "governance" / "daily_pipeline_registry.yaml"


def test_registry_has_no_duplicate_active_orders() -> None:
    """No two active (non-archived, non-on_demand) steps share an ``order`` value.

    The typed ``CompiledPipeline.validate()`` enforces this at load time;
    this test is the YAML-level guard that catches the regression before
    the compiler runs.
    """
    with open(_REGISTRY) as f:
        registry = yaml.safe_load(f)
    steps = registry.get("steps", {})
    defaults = registry.get("_defaults", {})
    default_schedule = defaults.get("schedule", "daily")
    orders: dict[float, str] = {}
    duplicates: list[str] = []
    for step_id, step in steps.items():
        if not isinstance(step, dict):
            continue
        status = step.get("status", "active")
        if status in {"archived", "inactive"}:
            continue
        schedule = step.get("schedule", default_schedule)
        if schedule == "on_demand":
            continue
        order = step.get("order")
        if order is None:
            continue
        order = float(order)
        if order in orders:
            duplicates.append(f"{step_id} (order={order}) duplicates {orders[order]}")
        else:
            orders[order] = step_id
    assert not duplicates, f"Duplicate active step orders: {duplicates}"


def test_invalid_spec_is_rejected_before_execution_plan_is_returned(tmp_path: Path) -> None:
    """A malformed registry must fail in compilation before an executor can start."""
    from system_runtime.paths import WorkspacePaths
    from system_runtime.pipeline import PipelineSpecError, load_pipeline

    root = tmp_path / "workspace"
    (root / "governance").mkdir(parents=True)
    (root / "protocols").mkdir()
    shutil.copy2(_REGISTRY, root / "governance/daily_pipeline_registry.yaml")
    shutil.copy2(
        _REGISTRY.parents[1] / "protocols/pipeline_spec.schema.json",
        root / "protocols/pipeline_spec.schema.json",
    )
    registry = yaml.safe_load(
        (root / "governance/daily_pipeline_registry.yaml").read_text(encoding="utf-8")
    )
    active = [
        step
        for step in registry["steps"].values()
        if step.get("status", "active") not in {"archived", "inactive"}
        and step.get("schedule", registry["_defaults"].get("schedule")) != "on_demand"
    ]
    active[1]["order"] = active[0]["order"]
    (root / "governance/daily_pipeline_registry.yaml").write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(PipelineSpecError, match="duplicate active step order values"):
        load_pipeline(WorkspacePaths(root=root))


def test_compiled_plan_type_exists() -> None:
    from system_runtime.pipeline import CompiledPlan  # noqa: F401


def test_compiled_plan_has_stable_digest_and_failure_interpreter() -> None:
    from system_runtime.paths import WorkspacePaths
    from system_runtime.pipeline import load_pipeline

    plan = load_pipeline(WorkspacePaths(root=_REGISTRY.parents[1]))
    assert len(plan.plan_digest) == 64
    assert plan.plan_digest == load_pipeline(WorkspacePaths(root=_REGISTRY.parents[1])).plan_digest
    decision = plan.interpret_failure("judgment_layer", [])
    assert decision["action"] == "run"


def test_execution_profiles_are_compiled_from_the_same_registry() -> None:
    from system_runtime.paths import WorkspacePaths
    from system_runtime.pipeline import load_pipeline

    plan = load_pipeline(WorkspacePaths(root=_REGISTRY.parents[1]))
    expected_profiles = {
        "refresh_current",
        "work_cycle_quick_render",
        "work_cycle_standard_core",
        "work_cycle_always",
    }
    assert set(plan.profiles) == expected_profiles
    assert plan.projection("refresh_current")[0].step_id == "neutral_pressure_measurement"
    assert plan.projection("work_cycle_quick_render")[-1].step_id == "build_data_gaps"
    assert all(
        step.status not in {"archived", "inactive"}
        for profile in plan.profiles
        for step in plan.projection(profile)
    )


def test_refresh_and_work_cycle_entrypoints_have_no_local_step_lists() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "packages/orchestration/orchestration/ops/refresh_chain.py",
        root / "packages/orchestration/orchestration/runner.py",
        root / "scripts/refresh_output_current.py",
        root / "scripts/run_work_cycle.py",
    ]
    forbidden = ("REFRESH_PRODUCER_STEPS", "STANDARD_STEPS", "QUICK_SCRIPTS")
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), source_path


def test_shared_panel_edges_are_explicit() -> None:
    """Panel ordering must not depend on path-prefix inference."""
    from system_runtime.paths import WorkspacePaths
    from system_runtime.pipeline import load_pipeline

    root = _REGISTRY.parents[1]
    registry = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))
    expected = {
        "refresh_cross_asset_panel": ["harvester"],
        "etf_refresh": ["refresh_cross_asset_panel"],
        "paper_portfolio": ["neutral_pressure_measurement", "trade_decision"],
        "strategy_lab_shadow": ["neutral_pressure_measurement"],
        "baseline_comparison": ["neutral_pressure_measurement"],
    }
    for step_id, dependencies in expected.items():
        assert registry["steps"][step_id]["depends_on"] == dependencies

    plan = load_pipeline(WorkspacePaths(root=root))
    for step_id, dependencies in expected.items():
        assert list(plan.edges[step_id]) == dependencies


def test_domain_operator_registry_is_governance_display_only() -> None:
    """The domain registry may inform audits, but never selects execution."""
    from system_runtime.paths import WorkspacePaths
    from system_runtime.pipeline import load_pipeline

    root = _REGISTRY.parents[1]
    operator_registry = yaml.safe_load(
        (root / "governance/operator_registry.yaml").read_text(encoding="utf-8")
    )
    authority = operator_registry["authority"]
    assert authority == {
        "role": "governance_display_only",
        "execution_authority": False,
        "can_affect_core_judgment": False,
    }

    plan = load_pipeline(WorkspacePaths(root=root))
    audit_step = plan.step("operator_registry_audit")
    assert audit_step.affects_core_judgment is False
    assert audit_step.failure_behavior == "continue_with_warning"
    assert audit_step.outputs
    assert all(path.startswith("Output/quality/") for path in audit_step.outputs)

    execution_roots = (
        root / "system_runtime",
        root / "system_cli",
        root / "packages/orchestration/orchestration",
        root / "scripts",
    )
    audit_script = root / "scripts/commands/weekly/operator_registry_audit.py"
    forbidden_reference = "governance/operator_registry.yaml"
    references: list[Path] = []
    for execution_root in execution_roots:
        for source_path in execution_root.rglob("*.py"):
            if source_path == audit_script:
                continue
            if forbidden_reference in source_path.read_text(encoding="utf-8"):
                references.append(source_path.relative_to(root))
    assert references == [], f"execution code references display-only registry: {references}"


def test_compiled_callable_receives_registry_command_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import _pipeline_runner as runner

    captured: dict[str, object] = {}

    def fake_run_callable_step(name: str, callable_spec: str, argv: list[str] | None = None):
        captured.update(name=name, callable_spec=callable_spec, argv=argv)
        return {"step": name, "status": "success"}

    monkeypatch.setattr(runner, "run_callable_step", fake_run_callable_step)
    result = runner.run_registry_step("record_daily_run_event")

    assert result["status"] == "success"
    assert captured["argv"] == ["--skip-if-unchanged"]


def test_executor_accepts_compiled_plan() -> None:
    """The sequence executor must accept CompiledPlan, not raw YAML."""
    import inspect

    from orchestration.sequence_executor import SequenceExecutor

    from system_runtime.pipeline import CompiledPlan

    sig = inspect.signature(SequenceExecutor.execute)
    params = list(sig.parameters.values())
    assert len(params) >= 2, "SequenceExecutor.execute must have self + plan params"
    # The second parameter (first non-self) must be annotated as CompiledPlan
    plan_param = params[1]
    assert (
        plan_param.annotation is CompiledPlan
        or str(plan_param.annotation).endswith("CompiledPlan")
    ), f"executor must accept CompiledPlan, got: {plan_param.annotation}"


def test_no_raw_yaml_sort_bypass() -> None:
    """The production executor must use CompiledPipeline, not raw-YAML order sorting.

    ``load_daily_run_sequence`` must not sort by ``order`` field directly;
    it must delegate to the typed compiler.  This test asserts the raw sort
    has been removed.
    """
    import inspect

    from scripts._daily_run_sequence import load_daily_run_sequence

    source = inspect.getsource(load_daily_run_sequence)
    assert "compiled.sort(key=" not in source, (
        "Raw YAML sort bypass still present in load_daily_run_sequence"
    )
