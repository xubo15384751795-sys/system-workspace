"""Contract tests for the daily signal pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _daily_run_sequence import load_daily_run_sequence, weekly_step_ids  # noqa: E402

REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"


def _daily_step_ids() -> list[str]:
    weekly = weekly_step_ids()
    return [
        str(step["id"])
        for step in load_daily_run_sequence()
        if step.get("id") and step["id"] not in weekly
    ]


def _load_registry_steps() -> dict:
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    return data.get("steps", {})


@pytest.fixture(scope="module")
def registry_steps() -> dict:
    return _load_registry_steps()


def test_daily_step_count_is_31():
    ids = _daily_step_ids()
    assert len(ids) == 31
    assert "refresh_cross_asset_panel" not in ids
    assert _load_registry_steps()["refresh_cross_asset_panel"]["schedule"] == "on_demand"
    assert "strategy_lab_shadow" in ids
    assert "shadow_outcomes_90d" in ids
    assert "evaluate_pending" in ids
    assert "paper_portfolio" in ids
    assert ids.index("paper_portfolio") == ids.index("record_trade_decision") + 1

def test_daily_steps_registered_in_pipeline_registry(registry_steps):
    missing = [sid for sid in _daily_step_ids() if sid not in registry_steps]
    assert missing == [], f"Daily steps missing from daily_pipeline_registry: {missing}"


def test_daily_steps_have_executable_command(registry_steps):
    no_command = []
    for sid in _daily_step_ids():
        entry = registry_steps.get(sid, {})
        execution = entry.get("execution") or {}
        has_command = bool(
            execution.get("current_command")
            or execution.get("future_callable")
            or entry.get("command")
        )
        if not has_command:
            no_command.append(sid)
    assert no_command == [], f"Daily steps without command: {no_command}"


def test_signal_blocking_steps_documented(registry_steps):
    """Steps that block promotion or core judgment must declare failure_behavior."""
    blocking = []
    for sid in _daily_step_ids():
        entry = registry_steps.get(sid, {})
        behavior = entry.get("failure_behavior", "")
        if behavior in ("block_promotion", "block_core_judgment", "block_current_readout"):
            blocking.append(sid)
    assert "judgment_promotion_gate" in blocking
    assert "judgment_layer" in _daily_step_ids()
    assert len(blocking) >= 3
