from __future__ import annotations

import unittest

import pandas as pd

from src._legacy.data.data_sources import MockDataSource
from src.derivation.proxy_builder import DefaultProxyBuilder
from src.proxies import structural_basket_map


class ProxyBuilderTests(unittest.TestCase):
    def test_build_from_mock_data_source(self) -> None:
        source = MockDataSource(seed=7)
        raw = source.fetch(["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"], "2026-01-01", "2026-03-01")
        builder = DefaultProxyBuilder()

        reading = builder.build(raw, "2026-03-01")
        self.assertEqual(reading.run_date, "2026-03-01")
        self.assertEqual(set(reading.available.keys()), {"M", "D", "K", "X", "X_PRE", "X_REALIZED"})
        self.assertTrue(all(isinstance(flag, bool) for flag in reading.available.values()))
        self.assertTrue(reading.available["X"])
        self.assertFalse(reading.available["X_PRE"])
        self.assertFalse(reading.available["X_REALIZED"])

    def test_build_handles_missing_columns(self) -> None:
        source = MockDataSource(seed=9)
        raw = source.fetch(["M_PROXY", "D_PROXY"], "2026-01-01", "2026-02-01")
        builder = DefaultProxyBuilder()

        reading = builder.build(raw, "2026-02-01")
        self.assertTrue(reading.available["M"])
        self.assertTrue(reading.available["D"])
        self.assertFalse(reading.available["K"])
        self.assertFalse(reading.available["X"])
        self.assertFalse(reading.available["X_PRE"])
        self.assertFalse(reading.available["X_REALIZED"])
        self.assertEqual(reading.directions["K"], "UNKNOWN")
        self.assertEqual(reading.directions["X"], "UNKNOWN")

    def test_build_engineered_proxy_baskets(self) -> None:
        idx = pd.date_range("2026-01-01", periods=5, freq="D")
        raw = pd.DataFrame(
            {
                "D_BID_ASK_SPREAD": [1, 2, 3, 4, 5],
                "D_HEDGE_BREADTH": [5, 4, 3, 2, 1],
                "D_FUNDING_STRESS": [1, 2, 3, 4, 5],
                "K_IV_DISTORTION": [1, 2, 3, 4, 5],
                "K_REALIZED_JUMP": [1, 1, 1, 2, 3],
                "K_TAIL_CONVEXITY": [2, 2, 3, 4, 6],
                "X_OBS_ASSETS": [1, 2, 3, 4, 5],
                "X_HIDDEN_LEVERAGE": [1, 1, 2, 3, 5],
                "X_SHADOW_FUNDING": [0, 1, 1, 2, 4],
                "M_PRICE_FUNDING_GAP": [0, 1, 1, 2, 4],
                "M_PRICE_VERIFIABILITY_GAP": [0, 1, 2, 3, 5],
                "M_PRICE_LIQUIDATION_GAP": [0, 0, 1, 3, 6],
            },
            index=idx,
        )

        reading = DefaultProxyBuilder().build(raw, "2026-01-05")

        self.assertTrue(all(reading.available[ch] for ch in ("M", "D", "K", "X", "X_PRE")))
        self.assertFalse(reading.available["X_REALIZED"])
        self.assertLess(reading.D or 0.0, -0.5)
        self.assertGreater(reading.K or 0.0, 0.5)
        self.assertGreater(reading.X or 0.0, 0.5)
        self.assertGreater(reading.X_PRE or 0.0, 0.5)
        self.assertIsNone(reading.X_REALIZED)
        self.assertGreater(reading.M or 0.0, 0.5)
        self.assertEqual(reading.directions["D"], "WORSENING")
        self.assertEqual(reading.directions["K"], "WORSENING")
        self.assertIn("D_MARKET_DEPTH", reading.components)
        self.assertIn("M_PRICE_LIQUIDATION_GAP", reading.components)
        self.assertIn("D_STRESS", reading.components)

    def test_structural_proxy_groups_preserve_anchor_mismatch_dimensions(self) -> None:
        idx = pd.date_range("2026-01-01", periods=5, freq="D")
        raw = pd.DataFrame(
            {
                "M_MARKET_POLICY_PATH_GAP": [0, 1, 2, 3, 4],
                "M_REPO_IMPLIED_FUNDING_GAP": [0, 1, 2, 4, 7],
                "M_SWAP_SPREAD": [0, 1, 3, 4, 5],
                "M_CDS_BOND_BASIS": [0, 0, 1, 2, 3],
                "M_ACCOUNTING_MARKET_VALUE_GAP": [0, 2, 4, 6, 9],
                "D_ORDER_BOOK_DEPTH": [5, 4, 3, 2, 1],
                "D_HEDGE_AVAILABILITY": [5, 4, 3, 2, 1],
                "D_DEALER_CAPACITY": [5, 4, 3, 2, 1],
                "D_ETF_NAV_DISLOCATION": [0, 1, 2, 3, 4],
                "K_SKEW_SLOPE": [0, 1, 2, 3, 5],
                "K_REALIZED_JUMP": [0, 1, 1, 2, 4],
                "K_CRASH_SKEW": [0, 1, 2, 4, 8],
                "K_COVARIANCE_EIGENVECTOR_ROTATION": [0, 0, 1, 3, 6],
                "X_MARGIN_DEBT": [0, 1, 2, 3, 4],
                "X_PRIVATE_CREDIT_GROWTH": [0, 1, 1, 2, 4],
                "X_MATURITY_WALL": [0, 1, 2, 3, 5],
                "X_HTM_UNREALIZED_LOSS_PROXY": [0, 1, 3, 6, 10],
            },
            index=idx,
        )

        reading = DefaultProxyBuilder().build(raw, "2026-01-05")

        self.assertTrue(all(reading.available[ch] for ch in ("M", "D", "K", "X", "X_PRE")))
        self.assertFalse(reading.available["X_REALIZED"])
        for key in (
            "M_POLICY_ANCHOR",
            "M_FUNDING_ANCHOR",
            "M_COLLATERAL_ANCHOR",
            "M_CREDIT_ANCHOR",
            "M_VERIFIABILITY_ANCHOR",
            "D_LIQUIDATION_PATHS",
            "K_TRANSITION_INSTABILITY",
            "X_VALUATION_LAG",
        ):
            self.assertIn(key, reading.components)
        self.assertGreater(reading.components["D_STRESS"] or 0.0, 0.5)

    def test_retired_tedrate_is_not_in_anchor_mismatch_basket(self) -> None:
        basket = structural_basket_map()
        m_ids = {
            spec["id"]
            for specs in basket["M"].values()
            for spec in specs
        }

        self.assertNotIn("TEDRATE", m_ids)

    def test_realized_shadow_support_is_separate_from_x_pre(self) -> None:
        idx = pd.date_range("2026-01-01", periods=5, freq="D")
        raw = pd.DataFrame(
            {
                "X_MARGIN_DEBT": [0, 1, 2, 3, 4],
                "primary_credit": [0, 0, 1, 4, 8],
            },
            index=idx,
        )

        reading = DefaultProxyBuilder().build(raw, "2026-01-05")

        self.assertTrue(reading.available["X_PRE"])
        self.assertTrue(reading.available["X_REALIZED"])
        self.assertTrue(reading.available["X"])
        self.assertIsNotNone(reading.X_PRE)
        self.assertIsNotNone(reading.X_REALIZED)

    def test_direct_d_proxy_low_value_is_worsening(self) -> None:
        raw = pd.DataFrame({"D_PROXY": [-1.0]}, index=pd.to_datetime(["2026-01-01"]))

        reading = DefaultProxyBuilder().build(raw, "2026-01-01")

        self.assertEqual(reading.directions["D"], "WORSENING")

    def test_future_rows_do_not_change_as_of_proxy_output(self) -> None:
        idx = pd.date_range("2026-01-01", periods=8, freq="D")
        raw = pd.DataFrame(
            {
                "M_MARKET_POLICY_PATH_GAP": [0, 1, 2, 3, 4, 1000, 1000, 1000],
                "M_REPO_IMPLIED_FUNDING_GAP": [0, 1, 2, 3, 5, 1000, 1000, 1000],
                "M_SWAP_SPREAD": [0, 1, 2, 4, 6, 1000, 1000, 1000],
                "M_CDS_BOND_BASIS": [0, 1, 1, 2, 4, 1000, 1000, 1000],
                "M_ACCOUNTING_MARKET_VALUE_GAP": [0, 1, 3, 5, 8, 1000, 1000, 1000],
            },
            index=idx,
        )
        as_of = "2026-01-05"
        builder = DefaultProxyBuilder()

        baseline = builder.build(raw.loc[:as_of], as_of)
        with_future_tail = builder.build(raw, as_of)

        self.assertEqual(with_future_tail.M, baseline.M)
        self.assertEqual(with_future_tail.components["M_POLICY_ANCHOR"], baseline.components["M_POLICY_ANCHOR"])


if __name__ == "__main__":
    unittest.main()
