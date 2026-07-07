from __future__ import annotations

import unittest

from src.data.adapters import CBOESeriesAdapter, CFTCPositionAdapter, ECBSeriesAdapter, StooqSeriesAdapter, TiingoSeriesAdapter
from src.data.contracts import PositionRequest, SeriesRequest
from src.data.gateway import create_data_hub


class _ECBHTTP:
    def get_text(self, url: str, headers=None) -> str:
        _ = (url, headers)
        return "\n".join(
            [
                "TIME_PERIOD,OBS_VALUE",
                "2026-01-01,1.10",
                "2026-01-02,1.12",
            ]
        )


class _CFTCHTTP:
    def get_json(self, url: str, headers=None):
        _ = (url, headers)
        return [
            {
                "report_date_as_yyyy_mm_dd": "2026-01-05",
                "market_and_exchange_names": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
                "cftc_contract_market_code": "099741",
                "noncomm_positions_long_all": "1000",
                "noncomm_positions_short_all": "700",
                "noncomm_positions_spreading_all": "50",
                "open_interest_all": "5000",
            }
        ]


class _CSVHTTP:
    def get_text(self, url: str, headers=None) -> str:
        _ = (url, headers)
        return "\n".join(
            [
                "Date,Open,High,Low,Close,Volume",
                "2026-01-02,10,11,9,10.5,1000",
                "2026-01-05,10.5,12,10,11.5,1200",
            ]
        )


class _TiingoHTTP:
    def get_json(self, url: str, headers=None):
        _ = (url, headers)
        return [
            {"date": "2026-01-02T00:00:00.000Z", "close": 10.4, "adjClose": 10.2},
            {"date": "2026-01-05T00:00:00.000Z", "close": 11.4, "adjClose": 11.2},
        ]


class DataHubTests(unittest.TestCase):
    def test_create_data_hub_in_mock_mode_supports_all_primary_fetch_types(self) -> None:
        config = {"project_name": "Structural Deformation Research System", "mock_seed": 42}
        hub = create_data_hub(config=config, use_mock=True)

        providers = hub.available_providers()
        series = hub.fetch_series(
            [{"provider": "fred", "series_id": "DFF"}],
            start="2026-01-01",
            end="2026-01-10",
        )
        filings = hub.fetch_filings(
            [
                {
                    "provider": "sec",
                    "cik": "320193",
                    "channel": "X",
                    "measurement_block": "verifiability",
                    "evidence_role": "validation",
                    "jurisdiction_or_scope": "issuer_core",
                }
            ],
            start="2026-01-01",
            end="2026-01-10",
        )
        positions = hub.fetch_positions(
            [
                {
                    "provider": "cftc",
                    "resource": "dummy",
                    "market_name": "Mock Market",
                    "channel": "D",
                    "measurement_block": "hedge_breadth",
                    "evidence_role": "validation",
                    "jurisdiction_or_scope": "us_futures",
                }
            ],
            start="2026-01-01",
            end="2026-01-10",
        )

        self.assertIn("fred", providers["series"])
        self.assertIn("sec", providers["filings"])
        self.assertIn("stooq", providers["series"])
        self.assertIn("tiingo", providers["series"])
        self.assertIn("cboe", providers["series"])
        self.assertIn("oecd", providers["series"])
        self.assertIn("bis", providers["series"])
        self.assertIn("imf", providers["series"])
        self.assertIn("ffiec", providers["series"])
        self.assertEqual(series.kind, "series")
        self.assertEqual(len(series.items), 1)
        self.assertEqual(series.items[0].metadata.get("preset_name"), "mismatch_policy_funding_gap_us")
        self.assertEqual(len(filings.items), 1)
        self.assertEqual(len(positions.items), 1)

    def test_ecb_adapter_parses_csvdata_response(self) -> None:
        adapter = ECBSeriesAdapter(http=_ECBHTTP())

        result = adapter.fetch_series(
            SeriesRequest(
                provider="ecb",
                dataset="EXR",
                series_id="D.USD.EUR.SP00.A",
                channel="M",
                measurement_block="funding_gap",
                evidence_role="validation",
                jurisdiction_or_scope="eurusd",
            ),
            start="2026-01-01",
            end="2026-01-10",
        )

        self.assertEqual(result.provider, "ecb")
        self.assertEqual(result.request_key, "D.USD.EUR.SP00.A")
        self.assertEqual(result.frame.shape, (2, 1))

    def test_cftc_adapter_normalizes_position_rows(self) -> None:
        adapter = CFTCPositionAdapter(http=_CFTCHTTP())

        items = adapter.fetch_positions(
            PositionRequest(
                provider="cftc",
                resource="dummy",
                market_name="EURO FX",
                channel="D",
                measurement_block="hedge_breadth",
                evidence_role="validation",
                jurisdiction_or_scope="us_futures",
            ),
            start="2026-01-01",
            end="2026-01-10",
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].market_code, "099741")
        self.assertEqual(items[0].long, 1000.0)
        self.assertEqual(items[0].short, 700.0)

    def test_ambiguous_series_requests_must_choose_structural_preset(self) -> None:
        config = {"project_name": "Structural Deformation Research System", "mock_seed": 42}
        hub = create_data_hub(config=config, use_mock=True)

        result = hub.fetch_series(
            [{"provider": "fred", "series_id": "VIXCLS"}],
            start="2026-01-01",
            end="2026-01-10",
        )

        self.assertEqual(len(result.items), 0)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("structurally ambiguous", result.errors[0].message)

    def test_stooq_adapter_parses_daily_csv(self) -> None:
        adapter = StooqSeriesAdapter(http=_CSVHTTP())

        result = adapter.fetch_series(
            SeriesRequest(
                provider="stooq",
                series_id="spy.us",
                channel="K",
                measurement_block="market_price",
                evidence_role="proxy",
            ),
            start="2026-01-01",
            end="2026-01-10",
        )

        self.assertEqual(result.provider, "stooq")
        self.assertEqual(result.frame.shape, (2, 1))
        self.assertAlmostEqual(float(result.frame.iloc[-1, 0]), 11.5)

    def test_tiingo_adapter_parses_price_rows(self) -> None:
        adapter = TiingoSeriesAdapter(api_key="demo", http=_TiingoHTTP())

        result = adapter.fetch_series(
            SeriesRequest(
                provider="tiingo",
                series_id="SPY",
                field="adjClose",
                channel="K",
                measurement_block="market_price",
                evidence_role="validation",
            ),
            start="2026-01-01",
            end="2026-01-10",
        )

        self.assertEqual(result.provider, "tiingo")
        self.assertEqual(result.frame.shape, (2, 1))
        self.assertAlmostEqual(float(result.frame.iloc[0, 0]), 10.2)

    def test_cboe_adapter_parses_vix_csv(self) -> None:
        adapter = CBOESeriesAdapter(http=_CSVHTTP())

        result = adapter.fetch_series(
            SeriesRequest(
                provider="cboe",
                dataset="vix",
                field="Close",
                channel="K",
                measurement_block="volatility_surface",
                evidence_role="proxy",
            ),
            start="2026-01-01",
            end="2026-01-10",
        )

        self.assertEqual(result.provider, "cboe")
        self.assertEqual(result.frame.shape, (2, 1))


if __name__ == "__main__":
    unittest.main()
