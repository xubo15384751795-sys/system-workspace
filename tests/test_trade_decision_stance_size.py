"""Unit tests for Phase 4 stance × size trade decision."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "workbench" / "src"))

from workbench.judgment.trade_decision import (
    compose_trade_fields,
    determine_size,
    determine_stance,
    snap_size,
    step_down_size,
)


def test_stance_exit_is_risk_off() -> None:
    assert determine_stance({}, {"state": "EXIT", "position": 0.0}) == "RISK_OFF"


def test_stance_invalid_position_fails_closed() -> None:
    assert determine_stance({}, {"state": "FULL", "position": "not-a-number"}) == "RISK_OFF"


def test_stance_three_channels_deteriorating_is_risk_reduce() -> None:
    vg = {
        "state": "FULL",
        "position": 1.0,
        "n_deteriorating": 3,
        "velocity_20d": {"M": 0.5, "D": 0.4, "K": 0.3, "X": 0.0},
    }
    assert determine_stance(None, vg) == "RISK_REDUCE"


def test_stance_full_without_deterioration_is_risk_on() -> None:
    vg = {
        "state": "FULL",
        "position": 1.0,
        "n_deteriorating": 1,
        "velocity_20d": {"M": 0.5, "D": 0.0, "K": 0.0, "X": 0.0},
    }
    assert determine_stance(None, vg) == "RISK_ON"


def test_stance_without_channel_velocities_does_not_invent_reduce() -> None:
    assert determine_stance(None, {"state": "FULL", "position": 1.0}) == "RISK_ON"
    assert determine_stance(None, {"state": "EXIT", "position": 0.0}) == "RISK_OFF"


def test_size_discounts_and_snaps() -> None:
    size = determine_size(
        {
            "k_verdict": "FAIL",
            "x_verdict": "PASS",
            "hmm_grade": "HIGH",
            "caselab_label": "strong",
            "has_approved_paper": True,
            "paper_stale": False,
            "promotion_hard_blocked": False,
        }
    )
    assert size == 0.5


def test_size_paper_stale_steps_down() -> None:
    base = determine_size(
        {
            "k_verdict": "PASS",
            "x_verdict": "PASS",
            "hmm_grade": "HIGH",
            "caselab_label": "strong",
            "has_approved_paper": True,
            "paper_stale": False,
            "promotion_hard_blocked": False,
        }
    )
    stale = determine_size(
        {
            "k_verdict": "PASS",
            "x_verdict": "PASS",
            "hmm_grade": "HIGH",
            "caselab_label": "strong",
            "has_approved_paper": True,
            "paper_stale": True,
            "promotion_hard_blocked": False,
        }
    )
    assert base == 1.0
    assert stale == 0.5
    assert step_down_size(1.0) == 0.5


def test_size_hard_promotion_block_zeros() -> None:
    size = determine_size(
        {
            "k_verdict": "PASS",
            "x_verdict": "PASS",
            "hmm_grade": "HIGH",
            "caselab_label": "strong",
            "has_approved_paper": True,
            "paper_stale": False,
            "promotion_hard_blocked": True,
        }
    )
    assert size == 0.0


def test_compose_watch_when_data_unavailable() -> None:
    out = compose_trade_fields(
        stance="RISK_ON",
        size=1.0,
        data_available=False,
        risk_notes=["missing"],
    )
    assert out["decision"] == "WATCH"
    assert out["size"] == 0.0


def test_compose_effective_size_stance_weight() -> None:
    on = compose_trade_fields(stance="RISK_ON", size=1.0, data_available=True)
    reduce = compose_trade_fields(stance="RISK_REDUCE", size=1.0, data_available=True)
    off = compose_trade_fields(stance="RISK_OFF", size=1.0, data_available=True)
    assert on["effective_size"] == 1.0
    assert reduce["effective_size"] == 0.5
    assert off["effective_size"] == 0.0
    assert snap_size(0.3) in (0.25, 0.5)
