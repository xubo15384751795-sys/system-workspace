"""Phase A failure-propagation tests.

Verifies the runtime enforcement of the registry's block_* failure_behavior:
when the neutral pressure measurement fails, its descendants
(judgment_layer, trade_decision, paper_portfolio) are recorded as
``blocked_upstream`` and NEVER executed - rather than silently running against
stale/previous-run artifacts.

These tests do not run the real pipeline steps; they patch ``execute_step`` so
only the propagation logic in ``execute_daily_sequence`` is exercised.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_executor():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(
        "_daily_run_executor", ROOT / "scripts" / "_daily_run_executor.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_daily_run_executor"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def exec_mod():
    return _load_executor()


def _make_ctx(exec_mod, executed: list[str]):
    """Build a DailyRunContext whose run_step_fn records what was executed."""
    args = SimpleNamespace(force_weekly=True, skip_harvester=False, skip_etf=False)
    ctx = exec_mod.DailyRunContext(
        args=args,
        start_time=datetime(2026, 7, 17),
        total_steps=100,
        run_step_fn=lambda *a, **k: {"status": "success"},
        record_fn=lambda *a, **k: None,
        benchmark_panel_path=ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet",
        run_id="test_bundle_run_id",
    )
    return ctx


def _status_map(results):
    return {r["step"]: r.get("status") for r in results}


class TestFailurePropagation:
    """Neutral pressure measurement failure blocks declared descendants."""

    def test_neutral_pressure_failure_blocks_chain(self, exec_mod, tmp_path):
        """When neutral measurement fails, judgment/trade/paper are
        blocked_upstream and never executed."""
        executed: list[str] = []

        def fake_execute_step(step_id, ctx):
            executed.append(step_id)
            if step_id == "neutral_pressure_measurement":
                return {"step": step_id, "status": "failed", "returncode": 1, "duration_s": 1.0}
            return {"step": step_id, "status": "success", "returncode": 0, "duration_s": 0.1}

        ctx = _make_ctx(exec_mod, executed)
        with patch.object(exec_mod, "execute_step", side_effect=fake_execute_step):
            results = exec_mod.execute_daily_sequence(ctx)

        status = _status_map(results)

        # Root failure recorded.
        assert status.get("neutral_pressure_measurement") == "failed"
        assert "neutral_pressure_measurement" in executed

        # Declared descendants must be blocked, not executed.
        for descendant in ("judgment_layer", "trade_decision", "paper_portfolio"):
            assert status.get(descendant) == "blocked_upstream", (
                f"{descendant} should be blocked_upstream, got {status.get(descendant)!r}"
            )
            assert descendant not in executed, (
                f"{descendant} must NOT be executed when upstream failed, but was"
            )

        # blocked_by lineage recorded on each descendant.
        for r in results:
            if r.get("status") == "blocked_upstream":
                assert r.get("blocked_by"), "blocked_upstream step must record blocked_by"

    def test_clean_run_does_not_block(self, exec_mod):
        """When no upstream fails, no step is blocked_upstream."""
        executed: list[str] = []

        def fake_execute_step(step_id, ctx):
            executed.append(step_id)
            return {"step": step_id, "status": "success", "returncode": 0, "duration_s": 0.1}

        ctx = _make_ctx(exec_mod, executed)
        with patch.object(exec_mod, "execute_step", side_effect=fake_execute_step):
            results = exec_mod.execute_daily_sequence(ctx)

        blocked = [r for r in results if r.get("status") == "blocked_upstream"]
        assert blocked == [], f"no steps should be blocked on a clean run, got {blocked}"

    def test_continue_with_warning_failure_does_not_propagate(self, exec_mod):
        """A continue_with_warning leaf that fails must NOT block descendants.

        We verify the propagates-failure predicate:
        - continue_with_warning steps (e.g. run_operator_detections) do NOT
          propagate failure to descendants.
        - blocking steps (neutral_pressure_measurement, paper_portfolio after
          Phase A upgrade to decision_adjacent_block) DO propagate.

        paper_portfolio was continue_with_warning before Phase A; it is now
        decision_adjacent_block (it feeds shadow promotion evidence, so its
        failure must block shadow descendants).
        """
        from _pipeline_dag import _propagates_failure

        # Non-propagating (leaf / advisory).
        assert _propagates_failure("run_operator_detections") is False
        assert _propagates_failure("hmm_stability_audit") is False
        # Propagating (block_* / hold_flat / decision_adjacent_block).
        assert _propagates_failure("neutral_pressure_measurement") is True
        assert _propagates_failure("paper_portfolio") is True


class TestPipelineDagEdges:
    """The DAG edges derived from registry contracts match the declared chain."""

    def test_declared_chain(self):
        from _pipeline_dag import upstream_of

        assert "neutral_pressure_measurement" in upstream_of("judgment_layer")
        assert "judgment_layer" in upstream_of("trade_decision")
        # paper_portfolio depends on both the trade decision and the neutral
        # pressure snapshot used by its requalification-only velocity gate.
        assert "trade_decision" in upstream_of("paper_portfolio")
        assert "neutral_pressure_measurement" in upstream_of("paper_portfolio")
