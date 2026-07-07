from __future__ import annotations

import time
import unittest

import pandas as pd

from src.core.interfaces import DataSource
from src._legacy.data.data_sources import (
    CompositeDataSource,
    DataSourceFactory,
    FederalReserveH41DataSource,
    ProxyAggregationDataSource,
    SECEDGARDataSource,
)
from src.data.gateway import DataHubBridge


class _StubSource(DataSource):
    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        idx = pd.date_range(start=start, end=end, freq="D")
        frame = pd.DataFrame(index=idx)
        for sid in series_ids:
            if sid == "FRED:VIXCLS":
                frame[sid] = [10.0 + i for i in range(len(idx))]
            elif sid == "FRED:BAMLH0A0HYM2":
                frame[sid] = [5.0 + i for i in range(len(idx))]
        return frame

    def available_series(self) -> list[str]:
        return ["FRED:VIXCLS", "FRED:BAMLH0A0HYM2"]


class _NamedSource(DataSource):
    def __init__(self, name: str, delay: float = 0.0) -> None:
        self.name = name
        self.delay = delay
        self.calls: list[tuple[list[str], str, str]] = []

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        self.calls.append((list(series_ids), start, end))
        if self.delay:
            time.sleep(self.delay)
        idx = pd.date_range(start=start, end=end, freq="D")
        return pd.DataFrame({self.name: range(len(idx))}, index=idx)

    def available_series(self) -> list[str]:
        return [self.name]


class _CountingSource(DataSource):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, str]] = []

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        self.calls.append((list(series_ids), start, end))
        idx = pd.date_range(start=start, end=end, freq="D")
        frame = pd.DataFrame(index=idx)
        for sid in series_ids:
            frame[sid] = range(len(idx))
        return frame

    def available_series(self) -> list[str]:
        return ["FRED:VIXCLS", "FRED:BAMLH0A0HYM2"]


class DataSourceSelectionTests(unittest.TestCase):
    def _base_config(self) -> dict:
        return {
            "mock_seed": 42,
            "data_sources": {
                "enabled": ["fred", "h41", "sec", "treasury"],
                "h41_csv_url": "",
                "h41_date_column": "date",
                "sec_user_agent": "",
            },
        }

    def test_factory_uses_datahub_bridge_when_use_mock_true(self) -> None:
        source = DataSourceFactory.build(config=self._base_config(), use_mock=True, fallback_seed=9)
        self.assertIsInstance(source, DataHubBridge)

    def test_factory_uses_datahub_bridge_for_real_sources(self) -> None:
        source = DataSourceFactory.build(config=self._base_config(), use_mock=False, fallback_seed=9)
        self.assertIsInstance(source, DataHubBridge)

    def test_h41_and_sec_fallback_without_endpoint_or_user_agent(self) -> None:
        h41 = FederalReserveH41DataSource(csv_url="", fallback_seed=11)
        sec = SECEDGARDataSource(user_agent="", fallback_seed=11)

        h41_frame = h41.fetch(["H41:btfp"], "2026-01-01", "2026-01-31")
        sec_frame = sec.fetch(["SEC:0000072971"], "2026-01-01", "2026-01-31")

        self.assertGreaterEqual(len(h41_frame), 1)
        self.assertEqual(list(h41_frame.columns), ["H41:btfp"])
        self.assertGreaterEqual(len(sec_frame), 1)
        self.assertEqual(list(sec_frame.columns), ["SEC:0000072971"])

    def test_proxy_aggregation_maps_component_series(self) -> None:
        source = ProxyAggregationDataSource(
            source=_StubSource(),
            proxy_series_map={"D_PROXY": ["FRED:VIXCLS", "FRED:BAMLH0A0HYM2"]},
        )

        frame = source.fetch(["D_PROXY"], "2026-01-01", "2026-01-05")

        self.assertEqual(list(frame.columns), ["D_PROXY"])
        self.assertEqual(len(frame), 5)
        self.assertTrue(frame["D_PROXY"].notna().any())

    def test_composite_fetches_sources_concurrently(self) -> None:
        slow_a = _NamedSource("A", delay=0.15)
        slow_b = _NamedSource("B", delay=0.15)
        source = CompositeDataSource([slow_a, slow_b], max_workers=2)

        t0 = time.perf_counter()
        frame = source.fetch(["A", "B"], "2026-01-01", "2026-01-03")
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.28)
        self.assertIn("A", frame.columns)
        self.assertIn("B", frame.columns)
        self.assertEqual(len(slow_a.calls), 1)
        self.assertEqual(len(slow_b.calls), 1)

    def test_proxy_aggregation_fetches_only_incremental_tail(self) -> None:
        backing = _CountingSource()
        source = ProxyAggregationDataSource(
            source=backing,
            proxy_series_map={"D_PROXY": ["FRED:VIXCLS", "FRED:BAMLH0A0HYM2"]},
        )

        first = source.fetch(["D_PROXY"], "2026-01-01", "2026-01-05")
        second = source.fetch(["D_PROXY"], "2026-01-01", "2026-01-07")

        self.assertEqual(len(first), 5)
        self.assertEqual(len(second), 7)
        self.assertEqual(len(backing.calls), 2)
        self.assertEqual(backing.calls[1][1:], ("2026-01-06", "2026-01-07"))


if __name__ == "__main__":
    unittest.main()
