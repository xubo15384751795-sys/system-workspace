from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.judgment_replay_audit import compute_forward_outcomes, evaluate_card


def test_forward_outcomes_use_future_rows_only_when_available() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    market = {"SPY": pd.Series([100.0, 101.0, 99.0, 102.0], index=dates)}

    outcomes = compute_forward_outcomes("2026-01-02", market, {"1d": 1, "1w": 5})

    assert outcomes["1d"]["status"] == "evaluated"
    spy_1d = outcomes["1d"]["metrics"]["SPY"]
    assert spy_1d["entry_date"] == "2026-01-02"
    assert spy_1d["exit_date"] == "2026-01-05"
    assert spy_1d["return_pct"] == 1.0
    assert outcomes["1w"]["status"] == "skipped_insufficient_forward_window"
    assert outcomes["1w"]["metrics"]["SPY"]["status"] == "insufficient_forward_window"


def test_evaluate_card_skips_without_elapsed_forward_window() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    market = {"SPY": pd.Series([100.0, 101.0], index=dates)}
    card = {
        "as_of": "2026-01-05",
        "decision": "WATCH_ONLY",
        "confidence": {"level": "low"},
        "claim_ceiling": "diagnostic_watch_only",
        "risk": ["CaseLab has no reliable historical analogy today."],
        "watch_window": {"1d": ["Confirm persistence."]},
    }

    result = evaluate_card(card, market)

    assert result["status"] == "skipped_insufficient_forward_window"
    assert result["evaluated_horizons"] == []
