from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.benchmarks.portfolio_baselines import (
    RegimeAllocationRule,
    buy_and_hold,
    channel_aware_allocation,
    head_to_head,
    regime_allocation,
    risk_parity,
    run_strategy_panel,
    static_sixty_forty,
    vol_target,
)


def _toy_prices(n: int = 1500, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    eq_ret = rng.normal(0.0006, 0.012, n)
    eq_ret[400:430] -= 0.01
    eq_ret[900:930] -= 0.008
    bd_ret = rng.normal(0.0002, 0.004, n)
    eq = 100.0 * np.exp(np.cumsum(eq_ret))
    bd = 100.0 * np.exp(np.cumsum(bd_ret))
    return pd.DataFrame({"equity": eq, "bond": bd}, index=idx)


def _toy_sigma(prices: pd.DataFrame) -> pd.Series:
    rolling_vol = prices["equity"].pct_change().rolling(60, min_periods=20).std()
    return (rolling_vol - rolling_vol.mean()).fillna(0.0).rename("SIGMA")


class PortfolioBaselineTests(unittest.TestCase):
    def test_buy_and_hold_returns_unit_equity_weight(self) -> None:
        prices = _toy_prices()
        result = buy_and_hold(prices, asset="equity")
        weights = result.weights["equity"].dropna()
        self.assertTrue((weights == 1.0).all())
        self.assertGreater(result.equity_curve.iloc[-1], 0.0)
        self.assertIn("sharpe", result.metrics)

    def test_sixty_forty_weights_sum_to_one_on_rebalance(self) -> None:
        prices = _toy_prices()
        result = static_sixty_forty(prices)
        rebal = result.weights[(result.weights["equity"] > 0) | (result.weights["bond"] > 0)]
        sums = rebal.sum(axis=1)
        self.assertTrue((np.isclose(sums, 1.0)).all())

    def test_risk_parity_weights_inverse_to_vol(self) -> None:
        prices = _toy_prices()
        result = risk_parity(prices, lookback=40)
        rebal = result.weights[(result.weights["equity"] > 0) | (result.weights["bond"] > 0)]
        avg_eq = rebal["equity"].mean()
        avg_bd = rebal["bond"].mean()
        self.assertGreater(avg_bd, avg_eq)

    def test_vol_target_caps_equity_weight(self) -> None:
        prices = _toy_prices()
        result = vol_target(prices, target_annual_vol=0.10, lookback=40)
        self.assertLessEqual(result.weights["equity"].max(), 1.51)
        self.assertGreaterEqual(result.weights["equity"].min(), 0.0)

    def test_regime_allocation_three_states(self) -> None:
        prices = _toy_prices()
        sigma = _toy_sigma(prices)
        rule = RegimeAllocationRule(low_threshold=-0.5, high_threshold=0.5)
        result = regime_allocation(prices, sigma, rule=rule, name="test_regime")
        rebal = result.weights[(result.weights["equity"] > 0) | (result.weights["bond"] > 0)]
        eq_states = rebal["equity"].unique()
        self.assertGreaterEqual(len(set(np.round(eq_states, 2))), 2)

    def test_channel_aware_falls_back_when_channels_missing(self) -> None:
        prices = _toy_prices()
        sigma = _toy_sigma(prices)
        bad = pd.DataFrame(0.0, index=prices.index, columns=["foo"])
        result = channel_aware_allocation(prices, bad, sigma)
        self.assertEqual(result.name, "channel_aware")
        self.assertIn("Fallback", result.notes)

    def test_panel_compares_strategies(self) -> None:
        prices = _toy_prices()
        sigma = _toy_sigma(prices)
        channels = pd.DataFrame({
            "M": sigma.abs() * 0.5,
            "D": -sigma.abs() * 0.4,
            "K": sigma.abs() * 0.7,
            "X": sigma.abs() * 0.3,
        }, index=prices.index)
        nfci_proxy = sigma.rolling(20, min_periods=1).mean().rename("NFCI")
        comparison = run_strategy_panel(
            prices=prices,
            sigma=sigma,
            channels=channels,
            extra_signals={"nfci": nfci_proxy},
        )
        metrics = comparison.metrics_frame()
        self.assertTrue({"sharpe", "max_drawdown", "calmar"}.issubset(metrics.columns))
        self.assertIn("buy_and_hold_equity", metrics.index)
        self.assertIn("nfci_regime", metrics.index)

        deltas = head_to_head(comparison, baseline="sixty_forty")
        self.assertTrue("sixty_forty" in deltas.index)


if __name__ == "__main__":
    unittest.main()
