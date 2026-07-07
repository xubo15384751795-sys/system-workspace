from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from harvester.providers.sec import SecProvider

SEC_SUBMISSIONS_RESPONSE = {
    "cik": "0000072971",
    "entityType": "operating",
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000072971-26-000001",
                "0000072971-26-000002",
                "0000072971-26-000003",
            ],
            "filingDate": [
                "2026-01-15",
                "2026-01-15",
                "2026-01-20",
            ],
            "reportDate": [
                "2025-12-31",
                "2025-12-31",
                "2026-01-20",
            ],
            "form": ["10-Q", "8-K", "4"],
            "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.xml"],
        }
    },
}


def _mock_response(json_data: dict, status: int = 200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status
    resp.content = json.dumps(json_data).encode("utf-8")
    resp.text = json.dumps(json_data)
    resp.raise_for_status = MagicMock()
    if status >= 400:
        from requests.exceptions import HTTPError

        resp.raise_for_status.side_effect = HTTPError(response=resp)
    return resp


class TestSecProvider:
    def test_parse_filing_pulse(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response(SEC_SUBMISSIONS_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = SecProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["0000072971"])

            assert len(results) == 1
            r = results[0]
            assert r.provider == "sec"
            assert r.series_id == "0000072971"
            assert not r.frame.empty

            df = r.frame
            assert "date" in df.columns
            assert "value" in df.columns

            # 2026-01-15 had 2 filings, 2026-01-20 had 1
            row_jan15 = df[df["date"] == pd.Timestamp("2026-01-15")]
            assert len(row_jan15) == 1
            assert row_jan15["value"].iloc[0] == 2.0

            row_jan20 = df[df["date"] == pd.Timestamp("2026-01-20")]
            assert len(row_jan20) == 1
            assert row_jan20["value"].iloc[0] == 1.0

            assert df["unit"].iloc[0] == "filing_count"
            assert df["frequency"].iloc[0] == "daily"

    def test_cik_normalization(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response(SEC_SUBMISSIONS_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = SecProvider(data_root=str(tmp_path), cache=False)
            # CIK with leading zeros should be normalized
            results = prov.fetch_series(["72971"])
            assert len(results) == 1
            assert results[0].series_id == "72971"
            # Should have requested CIK0000072971
            url = mock_session.get.call_args[0][0]
            assert "CIK0000072971" in url

    def test_not_found(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, status=404)
            mock_session_cls.return_value = mock_session

            prov = SecProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["0000000000"])
            assert len(results) == 1
            assert results[0].fetch_error is not None
            assert "not found" in results[0].fetch_error.lower()

    def test_empty_filing_dates(self, tmp_path) -> None:
        empty_response = {
            "cik": "0000072971",
            "filings": {"recent": {"filingDate": [], "form": []}},
        }
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response(empty_response)
            mock_session_cls.return_value = mock_session

            prov = SecProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["0000072971"])
            assert len(results) == 1
            assert results[0].fetch_error is not None
            assert "no filing dates" in results[0].fetch_error

    def test_to_long_panel(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response(SEC_SUBMISSIONS_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = SecProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["0000072971"])
            panel = prov._to_long_panel(results)
            assert not panel.empty
            assert "series_id" in panel.columns
            assert panel["source_id"].iloc[0] == "sec"


class TestSecFilingPulseRegistryRouting:
    """Guard the registry-driven acquisition path for SEC_FILING_PULSE.

    Regression: SEC_FILING_PULSE had no ``source_series_id``, so registry
    routing passed the canonical_id string "SEC_FILING_PULSE" to SecProvider,
    which treated it as a CIK and built an invalid
    ``.../submissions/CIK000SEC_FILING_PULSE.json`` URL (404). The registry
    entry now pins ``source_series_id: "0000072971"`` so the canonical id is
    resolved to a real CIK before it reaches the provider.
    """

    def test_registry_pins_real_cik(self) -> None:
        from harvester.registry import load_registry

        series = load_registry().get("SEC_FILING_PULSE")
        assert series is not None
        # Provider-native id must be a real CIK, not the canonical_id string.
        assert series.source_series_id == "0000072971"
        assert series.source_series_id != series.canonical_id

    def test_filing_pulse_acquired_through_registry(self, tmp_path) -> None:
        from harvester.official import fetch_official_series_from_registry

        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response(SEC_SUBMISSIONS_RESPONSE)
            mock_session_cls.return_value = mock_session

            panel = fetch_official_series_from_registry(
                data_root=str(tmp_path),
                providers=["sec"],
                cache=False,
            )

            # Every SEC submissions URL must use the real CIK; the literal
            # canonical id must never leak into a request URL.
            requested_urls = [call.args[0] for call in mock_session.get.call_args_list]
            submissions_urls = [u for u in requested_urls if "/submissions/" in u]
            assert submissions_urls, "registry routing never hit the SEC submissions endpoint"
            assert any("CIK0000072971.json" in u for u in submissions_urls)
            assert all("SEC_FILING_PULSE" not in u for u in requested_urls)

        # The filing-pulse rows land in the panel under the canonical SEC id.
        assert not panel.empty
        pulse = panel[panel["source_series_id"] == "0000072971"]
        assert not pulse.empty
        assert set(pulse["series_id"].unique()) == {"SEC:0000072971"}
        assert (pulse["source_id"] == "sec").all()
        assert (pulse["quality_flag"] == 0).all()

        # 2026-01-15 had 2 filings, 2026-01-20 had 1 (mirrors the provider test).
        row_jan15 = pulse[pulse["date"] == pd.Timestamp("2026-01-15")]
        assert row_jan15["value"].iloc[0] == 2.0
        row_jan20 = pulse[pulse["date"] == pd.Timestamp("2026-01-20")]
        assert row_jan20["value"].iloc[0] == 1.0
