from __future__ import annotations

import tempfile
import unittest

from src._legacy.data.data_sources import FREDDataSource


class _GraphHTTP:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        _ = headers
        self.calls.append(url)
        return "\n".join(
            [
                "observation_date,VIXCLS",
                "2026-01-01,20.0",
                "2026-01-02,21.5",
                "2026-01-03,.",
            ]
        )


class FREDDataIngestionTests(unittest.TestCase):
    def test_fetch_unprefixed_without_api_key_falls_back_to_mock(self) -> None:
        source = FREDDataSource(api_key=None, fallback_seed=21)
        frame = source.fetch(["M_PROXY", "D_PROXY"], "2026-01-01", "2026-02-01")

        self.assertEqual(list(frame.columns), ["M_PROXY", "D_PROXY"])
        self.assertGreaterEqual(len(frame), 1)

    def test_fetch_without_api_key_uses_graph_csv_for_fred_series(self) -> None:
        http = _GraphHTTP()
        with tempfile.TemporaryDirectory() as tmpdir:
            source = FREDDataSource(api_key=None, http=http, cache_dir=tmpdir)

            frame = source.fetch(["FRED:VIXCLS"], "2026-01-01", "2026-01-31")

        self.assertEqual(list(frame.columns), ["FRED:VIXCLS"])
        self.assertEqual(len(frame), 2)
        self.assertEqual(float(frame.iloc[0]["FRED:VIXCLS"]), 20.0)
        self.assertEqual(len(http.calls), 1)

    def test_available_series_contains_core_channels(self) -> None:
        source = FREDDataSource(api_key=None)
        names = source.available_series()

        self.assertIn("M_PROXY", names)
        self.assertIn("D_PROXY", names)
        self.assertIn("K_PROXY", names)
        self.assertIn("X_PROXY", names)


if __name__ == "__main__":
    unittest.main()
