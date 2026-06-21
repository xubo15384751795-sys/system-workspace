from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import historical_validation_suite as suite  # noqa: E402


def test_direction_metric_uses_negative_as_bullish(monkeypatch) -> None:
    monkeypatch.setattr(suite, "MIN_EVAL_ROWS", 1)
    signal = pd.Series([-1.0, 1.0, -0.5, 0.7])
    target_up = pd.Series([True, False, True, False])

    metric = suite._direction_metric(signal < 0, target_up, signal=signal)

    assert metric["n"] == 4
    assert metric["agreement"] == 1.0


def test_sign_disagreement_detects_split_and_unanimous_rows() -> None:
    channels = pd.DataFrame(
        {
            "M": [1.0, 1.0, -1.0],
            "D": [1.0, -1.0, -1.0],
            "K": [1.0, 1.0, -1.0],
            "X": [1.0, -1.0, 1.0],
        }
    )

    result = suite._sign_disagreement(channels)

    assert result.iloc[0] == 0.0
    assert result.iloc[1] == 0.5
    assert result.iloc[2] == 0.25


def test_abs_max_router_selects_largest_available_channel(monkeypatch) -> None:
    monkeypatch.setattr(suite, "MIN_EVAL_ROWS", 1)
    df = pd.DataFrame(
        {
            "M": [-0.1, 0.2, -3.0],
            "D": [2.0, -0.1, 0.1],
            "K": [0.5, -2.5, 0.1],
            "X": [0.4, 0.3, 0.2],
            "ABS_MAX": ["D", "K", "M"],
            "fwd_up_5d": [False, True, True],
        }
    )

    metric = suite._abs_max_direction_metric(df, "fwd_up_5d")

    assert metric["n"] == 3
    assert metric["agreement"] == 1.0
