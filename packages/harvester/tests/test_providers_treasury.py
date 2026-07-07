from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from harvester.providers.treasury import TreasuryProvider

TREASURY_DEBT_RESPONSE = {
    "data": [
        {"record_date": "2026-01-02", "tot_pub_debt_out_amt": "35000000000000.00"},
        {"record_date": "2026-01-03", "tot_pub_debt_out_amt": "35100000000000.00"},
        {"record_date": "2026-01-06", "tot_pub_debt_out_amt": "35200000000000.00"},
    ]
}

TREASURY_DTS_RESPONSE = {
    "data": [
        {"record_date": "2026-01-02", "open_today_bal": "500000000000.00"},
        {"record_date": "2026-01-03", "open_today_bal": "510000000000.00"},
    ]
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


class TestTreasuryProvider:
    def test_parse_debt_to_penny(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response(TREASURY_DEBT_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = TreasuryProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["debt_to_penny:tot_pub_debt_out_amt"])

            assert len(results) == 1
            r = results[0]
            assert r.provider == "treasury"
            assert r.series_id == "debt_to_penny:tot_pub_debt_out_amt"
            assert len(r.frame) == 3
            assert r.frame["value"].iloc[0] == 35_000_000_000_000.00
            assert r.frame["unit"].iloc[0] == "usd"
            assert r.frame["frequency"].iloc[0] == "daily"

    def test_parse_daily_treasury_statement(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response(TREASURY_DTS_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = TreasuryProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["daily_treasury_statement:open_today_bal"])

            assert len(results) == 1
            r = results[0]
            assert r.provider == "treasury"
            assert r.series_id == "daily_treasury_statement:open_today_bal"
            assert len(r.frame) == 2
            assert r.frame["value"].iloc[0] == 500_000_000_000.00

    def test_invalid_series_format(self, tmp_path) -> None:
        prov = TreasuryProvider(data_root=str(tmp_path), cache=False)
        results = prov.fetch_series(["bad_format_no_colon"])
        assert len(results) == 1
        assert results[0].fetch_error is not None
        assert "invalid series_id format" in results[0].fetch_error

    def test_unknown_dataset(self, tmp_path) -> None:
        prov = TreasuryProvider(data_root=str(tmp_path), cache=False)
        results = prov.fetch_series(["unknown_dataset:some_field"])
        assert len(results) == 1
        assert results[0].fetch_error is not None
        assert "unknown dataset" in results[0].fetch_error

    def test_http_error(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, status=500)
            mock_session_cls.return_value = mock_session

            prov = TreasuryProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["debt_to_penny:tot_pub_debt_out_amt"])
            assert len(results) == 1
            assert results[0].fetch_error is not None

    def test_empty_response(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({"data": []})
            mock_session_cls.return_value = mock_session

            prov = TreasuryProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["debt_to_penny:tot_pub_debt_out_amt"])
            assert len(results) == 1
            assert results[0].fetch_error is not None
            assert "no data" in results[0].fetch_error

    def test_to_long_panel(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response(TREASURY_DEBT_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = TreasuryProvider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["debt_to_penny:tot_pub_debt_out_amt"])
            panel = prov._to_long_panel(results)
            assert not panel.empty
            assert "series_id" in panel.columns
            assert "source_id" in panel.columns
            assert panel["source_id"].iloc[0] == "treasury"
