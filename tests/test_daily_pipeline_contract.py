"""Contract tests for the daily signal pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verity.runtime._daily_run_sequence import (  # noqa: E402
    load_daily_run_sequence,
    weekly_step_ids,
)

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


def test_daily_step_count_is_32():
    ids = _daily_step_ids()
    assert len(ids) == 32
    # refresh_cross_asset_panel is the declared owner_step of the etf_panel
    # content_freshness check (3 trading days, decision_critical). Commit
    # 10acc44 added that check and set this step to on_demand in one change,
    # so the check could never be satisfied and the panel froze two days
    # later. governance/pipeline_schedule.md records it as daily since
    # 2026-07-11; keep the schedule and its owned check consistent.
    assert "refresh_cross_asset_panel" in ids
    assert _load_registry_steps()["refresh_cross_asset_panel"]["schedule"] == "daily"
    assert ids.index("refresh_cross_asset_panel") < ids.index("etf_refresh")
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


def test_strategy_lab_shadow_chain_declares_neutral_pressure_input():
    """Shadow producers must expose the snapshot consumed by data_loader.

    Both the daily shadow-card producer and its 90-day outcome backfill call
    ``load_aligned``/``load_signals``.  The registry must therefore expose the
    neutral-pressure snapshot as an input so the compiled graph carries the
    real upstream edge instead of relying on an undeclared filesystem read.
    """
    from system_runtime.paths import WorkspacePaths
    from system_runtime.pipeline import load_pipeline

    required = "Output/current/neutral_pressure_snapshot.json"
    registry = _load_registry_steps()
    for step_id in ("strategy_lab_shadow", "shadow_outcomes_90d"):
        entry = registry[step_id]
        declared = set(entry.get("input", []))
        declared.update((entry.get("contracts") or {}).get("inputs", []))
        assert required in declared, f"{step_id} hides its neutral-pressure dependency"

    plan = load_pipeline(WorkspacePaths(root=ROOT))
    assert "neutral_pressure_measurement" in plan.edges["strategy_lab_shadow"]
    assert "neutral_pressure_measurement" in plan.edges["shadow_outcomes_90d"]
    assert "strategy_lab_shadow" in plan.edges["shadow_outcomes_90d"]


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


def test_etf_refresh_declares_its_artifact_is_unmaintained(registry_steps):
    """etf_refresh must not read as a healthy producer while it cannot produce.

    Its command, scripts/refresh_etf_panel.py, exists — but the generator that
    command invokes, scripts/k_features_from_etf.py, was archived in 878bca4
    and is not in scripts/archive/ either, so update_k_features() logs and
    returns False every run. The registry still declares artifact_path
    Data/features/k_features_daily.csv, and the blocker text used to claim the
    script "may recompute features only".

    Delete this test if the generator is ever restored — at that point the
    step really does produce the artifact and artifact_status should go.
    """
    entry = registry_steps["etf_refresh"]
    generator = ROOT / "scripts" / "k_features_from_etf.py"

    if generator.exists():
        assert not entry.get("artifact_status"), (
            "k_features_from_etf.py is back; drop etf_refresh.artifact_status "
            "and this test."
        )
        return

    assert entry.get("artifact_status"), (
        "etf_refresh declares artifact_path "
        f"{entry.get('artifact_path')} but {generator.name} is missing, so it "
        "produces nothing. Record artifact_status rather than reading healthy."
    )
    blocker = str(entry.get("blocker", ""))
    assert "k_features_from_etf.py" in blocker, (
        "the blocker text must name the missing generator; it previously "
        "claimed the script 'may recompute features only'"
    )
