from __future__ import annotations

import unittest

import pandas as pd

from src.benchmarks.public_baselines import build_public_baselines
from src.signals.signal_decomposition import count_actionable_alerts
from src.validation.forward_targets import build_forward_targets
from src.validation.walk_forward import WalkForwardConfig, rolling_origin_oos_validate, thresholds_shift_by_origin


class PublicValidationUpgradeTests(unittest.TestCase):
    def test_public_baselines_share_interface(self) -> None:
        idx = pd.date_range("2020-01-03", periods=90, freq="W-FRI")
        frame = pd.DataFrame(
            {
                "VIXCLS": range(90),
                "NFCI": [0.1] * 90,
                "BAMLH0A0HYM2": [4.0] * 90,
                "T10Y2Y": [0.5] * 90,
                "STLFSI4": [0.0] * 90,
            },
            index=idx,
        )

        results = build_public_baselines(frame)

        expected = {"timestamp", "score", "percentile_score", "regime_label", "confidence", "source_features", "data_coverage"}
        self.assertIn("vix_only", results)
        self.assertIn("random_fixed_seed", results)
        self.assertTrue(all(expected.issubset(result.columns) for result in results.values()))

    def test_forward_targets_use_future_window_not_current_day(self) -> None:
        idx = pd.date_range("2024-01-01", periods=8, freq="B")
        frame = pd.DataFrame({"SPY": [100, 99, 80, 81, 82, 83, 84, 85], "VIXCLS": [10, 11, 12, 13, 14, 15, 16, 17]}, index=idx)

        targets = build_forward_targets(frame)

        self.assertAlmostEqual(targets.loc[idx[0], "forward_5d_equity_drawdown"], 0.20)
        self.assertAlmostEqual(targets.loc[idx[2], "forward_5d_equity_drawdown"], 0.0)

    def test_walk_forward_thresholds_shift_by_origin(self) -> None:
        idx = pd.date_range("2020-01-01", periods=80, freq="B")
        signal = pd.Series(list(range(40)) + list(range(40, 120, 2)), index=idx)
        target = signal > signal.rolling(20, min_periods=1).quantile(0.8)

        results = rolling_origin_oos_validate(
            signal,
            target,
            WalkForwardConfig(train_window=30, test_window=10, threshold_quantile=0.7, min_train=30),
        )

        self.assertGreater(len(results), 1)
        self.assertTrue(thresholds_shift_by_origin(results))

    def test_long_warnings_not_counted_as_actionable_successes(self) -> None:
        idx = pd.date_range("2024-01-01", periods=140, freq="B")
        warnings = pd.Series([True] * 130 + [False] * 10, index=idx)
        events = pd.Series([False] * 120 + [True] * 20, index=idx)

        metrics = count_actionable_alerts(warnings, events, max_warning_days=120)

        self.assertEqual(metrics["ignored_long_warnings"], 1.0)
        self.assertEqual(metrics["successful_actionable_alerts"], 0.0)


if __name__ == "__main__":
    unittest.main()
