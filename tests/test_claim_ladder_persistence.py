"""Claim ladder M/D persistence — unit tests for Tier 2 eligibility."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB_SRC = ROOT / "packages" / "workbench" / "src"
if str(WB_SRC) not in sys.path:
    sys.path.insert(0, str(WB_SRC))

from workbench.judgment.claim_ladder import _check_persistence


def test_persistence_counts_current_run_only():
    ok, count = _check_persistence([], "stress_relief")
    assert count == 1
    assert ok is False


def test_persistence_two_runs_same_direction():
    history = [{"md_direction": "stress_relief", "run_id": "prev"}]
    ok, count = _check_persistence(history, "stress_relief")
    assert count == 2
    assert ok is True


def test_persistence_breaks_on_direction_change():
    history = [
        {"md_direction": "stress_building", "run_id": "prev"},
        {"md_direction": "stress_relief", "run_id": "older"},
    ]
    ok, count = _check_persistence(history, "stress_relief")
    assert count == 1
    assert ok is False


def test_neutral_direction_never_persists():
    ok, count = _check_persistence(
        [{"md_direction": "neutral"}],
        "neutral",
    )
    assert count == 0
    assert ok is False
