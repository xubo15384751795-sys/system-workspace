from __future__ import annotations

import unittest

import pandas as pd

import pytest

pytestmark = pytest.mark.benchmark

from src.benchmarks import (
    DEFAULT_SERIES,
    HistoricalCase,
    RiskPolicy,
    build_structural_signals,
    evaluate_default_benchmarks,
    run_historical_replay,
    state_machine,
)
from src.benchmarks.public_baselines import available_public_baselines
from src.core.models import ProxyReading


class BenchmarkTests(unittest.TestCase):
    def test_default_benchmarks_return_named_comparators(self) -> None:
        proxy = ProxyReading(
            run_date="2026-04-14",
            M=0.5,
            D=-1.0,
            K=0.8,
            X=0.4,
            directions={"M": "STABLE", "D": "WORSENING", "K": "WORSENING", "X": "STABLE"},
            available={"M": True, "D": True, "K": True, "X": True},
            components={"M": 0.5, "D": -1.0, "K": 0.8, "X": 0.4},
        )

        scores = evaluate_default_benchmarks(proxy)

        self.assertEqual(
            {score.name for score in scores},
            {"volatility_only", "liquidity_only", "cfsi_like", "srisk_like", "bis_credit_gap_like"},
        )
        self.assertTrue(all(score.value >= 0.0 for score in scores))
        self.assertGreater(next(score.value for score in scores if score.name == "liquidity_only"), 0.0)

    def test_retired_tedrate_is_not_required_for_current_replay_or_public_baselines(self) -> None:
        self.assertNotIn("TEDRATE", DEFAULT_SERIES)
        self.assertIn("BAA10Y", DEFAULT_SERIES)
        frame = pd.DataFrame(
            {
                "VIXCLS": [20.0, 21.0],
                "BAMLH0A0HYM2": [3.0, 3.2],
                "BAA10Y": [2.0, 2.1],
                "NFCI": [-0.2, -0.1],
                "TEDRATE": [0.1, 0.2],
            },
            index=pd.date_range("2026-01-01", periods=2),
        )
        credit = next(item for item in available_public_baselines(frame, include_random=False) if item.name == "credit_spread_only")
        stress = next(item for item in available_public_baselines(frame, include_random=False) if item.name == "equal_weight_public_stress_basket")
        self.assertNotIn("TEDRATE", credit.source_features)
        self.assertNotIn("TEDRATE", stress.source_features)

    def test_historical_replay_compares_joint_and_single_channel_signals(self) -> None:
        dates = pd.date_range("2000-01-07", periods=90, freq="W-FRI")
        raw = pd.DataFrame(
            {
                "VIXCLS": [20.0] * 60 + [22.0] * 10 + [45.0] * 20,
                "BAA10Y": [2.0] * 50 + [2.5] * 20 + [4.0] * 20,
                "NFCI": [-0.5] * 50 + [0.2] * 20 + [2.0] * 20,
            },
            index=dates,
        )
        case = HistoricalCase(
            name="synthetic",
            start="2000-01-01",
            end="2001-12-31",
            event_date="2001-05-18",
            description="synthetic stress event",
        )

        metrics, signals, state_metrics = run_historical_replay(raw=raw, cases=(case,), threshold=1.0)

        self.assertEqual(
            {
                "joint_structural",
                "institutional_macro_stack",
                "institutional_fast_alert",
                "vix_only",
                "spread_only",
                "liquidity_only",
            },
            set(metrics["indicator"]),
        )
        self.assertTrue({"M", "D", "K", "X", "joint_structural", "institutional_macro_stack"}.issubset(signals.columns))
        self.assertTrue({"joint_structural_state", "joint_structural_action"}.issubset(signals.columns))
        self.assertTrue({"indicator", "event_state", "event_action"}.issubset(state_metrics.columns))
        self.assertGreater(metrics.loc[metrics["indicator"] == "joint_structural", "peak_pre_event"].iloc[0], 0.0)

    def test_build_structural_signals_requires_expected_fred_columns(self) -> None:
        raw = pd.DataFrame({"VIXCLS": [1.0, 2.0]}, index=pd.date_range("2000-01-01", periods=2))

        with self.assertRaises(ValueError):
            build_structural_signals(raw)

    def test_state_machine_uses_confirmation_and_hysteresis(self) -> None:
        signal = pd.Series([0.0, 1.2, 1.3, 1.1, 0.8, 0.5])
        states = state_machine(
            signal,
            policy=RiskPolicy(
                watch_enter=1.0,
                risk_off_enter=1.5,
                crisis_enter=2.5,
                exit_buffer=0.3,
                confirmation_window=3,
                confirmation_count=2,
                ewma_span=2,
            ),
        )

        self.assertEqual(states.iloc[0], "NORMAL")
        self.assertEqual(states.iloc[2], "WATCH")
        self.assertEqual(states.iloc[-1], "NORMAL")


if __name__ == "__main__":
    unittest.main()
