"""Acceptance skeleton for WP1B: single registry/compiler/executor authority.

Defines the contract that ``daily_pipeline_registry.yaml`` is the sole
execution authority, compiled by one ``Compiler`` into a ``CompiledPlan``
that the executor accepts.  Marked ``xfail(strict=True)`` until WP1B lands.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.xfail(
    strict=True,
    reason="WP1B: single compiler not yet implemented",
)

_REGISTRY = Path(__file__).resolve().parents[1] / "governance" / "daily_pipeline_registry.yaml"


def test_registry_steps_have_depends_on() -> None:
    """Every active step must declare explicit ``depends_on``, not just ``order``."""
    with open(_REGISTRY) as f:
        registry = yaml.safe_load(f)
    steps = registry.get("steps") or registry.get("pipeline_steps") or []
    missing = []
    for step in steps:
        if step.get("active", True) and "depends_on" not in step:
            missing.append(step.get("name", step.get("id", "?")))
    assert not missing, f"Steps missing explicit depends_on: {missing}"


def test_compiled_plan_type_exists() -> None:
    from system_runtime.pipeline import CompiledPlan  # noqa: F401


def test_executor_accepts_only_compiled_plan() -> None:
    """The sequence executor must not accept raw YAML; only CompiledPlan."""
    # The executor's run/execute signature must type-hint CompiledPlan,
    # not dict/str/raw YAML.
    import inspect

    from orchestration.sequence_executor import SequenceExecutor

    from system_runtime.pipeline import CompiledPlan

    sig = inspect.signature(SequenceExecutor.execute)
    params = list(sig.parameters.values())
    assert params, "SequenceExecutor.execute must have parameters"
    # The first non-self parameter must be annotated as CompiledPlan
    first_param = params[0]
    assert (
        first_param.annotation is CompiledPlan
        or str(first_param.annotation).endswith("CompiledPlan")
    ), f"executor must accept CompiledPlan, got: {first_param.annotation}"


def test_no_raw_yaml_sort_bypass() -> None:
    """The production executor must use CompiledPlan, not raw-YAML order sorting.

    The current ``_daily_run_sequence.load_daily_run_sequence`` still sorts by
    ``order`` field directly from YAML - this is the bypass WP1B removes.
    Until the compiler is the sole entry point, this test xfail-passes.
    """
    import inspect

    from scripts._daily_run_sequence import load_daily_run_sequence
    from system_runtime.pipeline import CompiledPlan  # noqa: F401

    # WP1B contract: load_daily_run_sequence must be demoted to a
    # generated-view helper only.  The production executor must not call it.
    # We assert it does NOT contain raw-YAML sort bypass - which is false
    # today (it does), so this xfail's.  When WP1B removes the sort, the
    # assertion becomes true -> xpass -> strict failure -> remove decorator.
    source = inspect.getsource(load_daily_run_sequence)
    assert "compiled.sort(key=" not in source, (
        "Raw YAML sort bypass still present in load_daily_run_sequence"
    )
