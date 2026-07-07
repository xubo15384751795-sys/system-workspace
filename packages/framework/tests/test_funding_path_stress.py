"""Tests for FUNDING_PATH_STRESS mechanism detector."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from src.operators.mechanism.funding_path_stress import FundingPathStressDetector

PANEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "Data"
    / "harvester"
    / "exports"
    / "latest"
    / "data"
    / "benchmark_panel.parquet"
)


def _panel_row(d: str, sid: str, val: float) -> dict:
    return {
        "date": d,
        "series_id": sid,
        "value": val,
        "source_id": "test",
        "source_series_id": sid.split(":")[-1],
        "quality_flag": 0,
    }


class FundingPathStressDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = FundingPathStressDetector()
        rows: list[dict] = []
        for i in range(30):
            d = f"2023-03-{i + 1:02d}"
            spread = 0.02 + i * 0.003
            rows.append(_panel_row(d, "DERIVED:SOFR_IORB_SPREAD", spread))
            rows.append(_panel_row(d, "FRED:WRESBAL", 3000.0 - i * 50))
            rows.append(_panel_row(d, "FRED:WTREGEN", 500.0 + i * 20))
            rows.append(_panel_row(d, "CBOE:MOVE", 120.0 + i))
        self.panel = pd.DataFrame(rows)

    def test_detect_returns_record(self) -> None:
        rec = self.detector.detect(self.panel, "2023-03-28")
        self.assertEqual(rec.operator, "FUNDING_PATH_STRESS")
        self.assertGreaterEqual(rec.activation, 0.0)
        self.assertLessEqual(rec.activation, 1.0)
        self.assertIn(rec.state, ("off", "watch", "active", "invalidated", "watch_only"))

    def test_missing_inputs_watch_only(self) -> None:
        empty = pd.DataFrame(columns=["date", "series_id", "value"])
        rec = self.detector.detect(empty, "2023-03-10")
        self.assertEqual(rec.state, "watch_only")

    def test_detect_range(self) -> None:
        records = self.detector.detect_range(self.panel, "2023-03-05", "2023-03-10")
        self.assertGreater(len(records), 0)


@unittest.skipUnless(PANEL_PATH.exists(), "benchmark panel required for calibration anchors")
class FundingPathStressCalibrationTests(unittest.TestCase):
    """Spec §5 anchors on the real harvester panel."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.detector = FundingPathStressDetector()
        cls.panel = pd.read_parquet(PANEL_PATH)

    def _max_activation(self, start: str, end: str) -> float:
        records = self.detector.detect_range(self.panel, start, end)
        return max((r.activation for r in records), default=0.0)

    def _days_above(self, start: str, end: str, threshold: float) -> int:
        records = self.detector.detect_range(self.panel, start, end)
        return sum(1 for r in records if r.activation >= threshold)

    def test_repo_spike_2019(self) -> None:
        self.assertGreaterEqual(self._max_activation("2019-09-13", "2019-10-10"), 0.85)
        self.assertGreaterEqual(self._days_above("2019-09-13", "2019-10-10", 0.85), 10)

    def test_covid_liquidity_2020_early(self) -> None:
        self.assertGreaterEqual(self._max_activation("2020-03-09", "2020-03-16"), 0.70)

    def test_svb_2023(self) -> None:
        self.assertGreaterEqual(self._days_above("2023-03-08", "2023-03-15", 0.65), 3)

    def test_rates_selloff_2023_false_positive(self) -> None:
        records = self.detector.detect_range(self.panel, "2023-10-19", "2023-11-01")
        self.assertTrue(all(r.activation <= 0.40 for r in records))


if __name__ == "__main__":
    unittest.main()
