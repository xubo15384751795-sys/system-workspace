"""Unit tests for net-cost backtest and bull-market velocity modulation."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strategy_lab.backtest import apply_transaction_costs, run_comparison
from strategy_lab.risk_gate import bull_relaxed_threshold_series, compute_velocity_gate


def test_apply_transaction_costs_reduces_returns_on_turnover() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="B")
    rets = pd.Series([0.01, 0.01, 0.01, 0.01, 0.01], index=idx)
    pos = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx)
    net, cost = apply_transaction_costs(rets, pos, cost_bps=3.0, slippage_bps=2.0)
    # Day1: enter 0→1 → turnover 1 → cost 5bp; Day3: exit 1→0 → cost 5bp
    assert cost.iloc[1] == pytest.approx(0.0005)
    assert cost.iloc[3] == pytest.approx(0.0005)
    assert float(net.sum()) < float((rets * pos.shift(1).fillna(0)).sum())


def test_run_comparison_zero_cost_matches_gross() -> None:
    idx = pd.date_range("2020-01-01", periods=60, freq="B")
    rets = pd.Series(0.001, index=idx)
    base = pd.Series(1.0, index=idx)
    overlay = pd.Series([1.0 if i % 10 else 0.0 for i in range(60)], index=idx)
    gross = run_comparison(rets, base, overlay, cost_bps=0.0, slippage_bps=0.0)
    assert "costs" in gross
    assert gross["costs"]["one_way_bps"] == 0.0


def test_bull_relaxed_threshold_raises_in_calm_bull() -> None:
    idx = pd.date_range("2020-01-01", periods=100, freq="B")
    # Steady uptrend, low vol
    close = pd.Series([100 * (1.001 ** i) for i in range(100)], index=idx)
    thr = bull_relaxed_threshold_series(close, base_threshold=1.5, bull_threshold=2.0)
    # After lookbacks warm up, should mostly be 2.0
    assert (thr.iloc[70:] == 2.0).mean() > 0.8


def test_bull_modulation_reduces_exits_vs_base() -> None:
    idx = pd.date_range("2015-01-01", periods=200, freq="B")
    # Mild deterioration that clears 1.5 but not 2.0 on one channel
    signals = pd.DataFrame(
        {
            "M": [0.0] * 200,
            "D": [0.0] * 200,
            "K": [0.0] * 180 + [1.7] * 20,  # late jump 1.7σ
            "X": [0.0] * 200,
        },
        index=idx,
    )
    close = pd.Series([100 * (1.002 ** i) for i in range(200)], index=idx)
    base = compute_velocity_gate(signals, velocity_threshold=1.5, bull_modulation=False)
    bull = compute_velocity_gate(
        signals,
        velocity_threshold=1.5,
        close=close,
        bull_modulation=True,
        bull_velocity_threshold=2.0,
    )
    # Without cofire, single-channel 1.7 triggers base (1.5) but not bull (2.0)
    assert float(base.iloc[-1]) == 0.0
    assert float(bull.iloc[-1]) == 1.0
