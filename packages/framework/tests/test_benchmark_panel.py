from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.benchmarks.benchmark_panel import (
    BENCHMARK_PANEL,
    DERIVED_SPREADS_RECIPE,
    all_fred_ids,
    build_derived_spreads,
    derived_spread,
    panel_by_category,
)


class BenchmarkPanelTests(unittest.TestCase):
    def test_panel_covers_required_categories(self) -> None:
        cats = {s.category for s in BENCHMARK_PANEL}
        self.assertTrue({"volatility", "liquidity", "credit", "term_structure", "composite_stress", "asset_price"}.issubset(cats))

    def test_fred_ids_unique_per_category(self) -> None:
        for category in ("volatility", "credit", "composite_stress"):
            ids = [s.fred_id for s in panel_by_category(category)]
            self.assertEqual(len(ids), len(set(ids)), f"duplicates in {category}")

    def test_all_fred_ids_dedupes_across_categories(self) -> None:
        ids = all_fred_ids()
        self.assertEqual(len(ids), len(set(ids)))

    def test_derived_spread_handles_missing_columns(self) -> None:
        frame = pd.DataFrame({"A": [1, 2, 3], "B": [0, 1, 2]})
        out = derived_spread(frame, "A", "B")
        self.assertTrue((out == pd.Series([1, 1, 1])).all())
        with self.assertRaises(KeyError):
            derived_spread(frame, "A", "C")

    def test_build_derived_spreads_skips_missing_recipes(self) -> None:
        idx = pd.date_range("2020-01-01", periods=10)
        frame = pd.DataFrame({"SOFR": np.linspace(0, 1, 10), "DTB3": np.linspace(0, 0.5, 10)}, index=idx)
        out = build_derived_spreads(frame, recipes=DERIVED_SPREADS_RECIPE)
        self.assertIn("SOFR_TBILL_3M", out.columns)
        self.assertNotIn("VIX_TERM_RATIO", out.columns)

    def test_vix_term_ratio_handles_zero(self) -> None:
        idx = pd.date_range("2020-01-01", periods=4)
        frame = pd.DataFrame({"VIXCLS": [20, 25, 30, 35], "VXVCLS": [22, 0, 28, 30]}, index=idx)
        out = build_derived_spreads(frame, recipes=(("VIX_TERM_RATIO", "VIXCLS", "VXVCLS"),))
        self.assertIn("VIX_TERM_RATIO", out.columns)
        self.assertTrue(np.isnan(out["VIX_TERM_RATIO"].iloc[1]))


if __name__ == "__main__":
    unittest.main()
