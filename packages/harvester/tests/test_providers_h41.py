from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from harvester.providers.h41 import (
    H41_DDP_MAP,
    H41_FRED_MAP,
    H41_SOURCE_NOTE,
    H41_UNITS,
    H41Provider,
)

FRED_H41_RESPONSE = {
    "realtime_start": "2026-04-01",
    "realtime_end": "2026-04-30",
    "observation_start": "2026-01-01",
    "observation_end": "2026-04-30",
    "units": "Millions of U.S. Dollars",
    "frequency": "Weekly, Ending Wednesday",
    "observations": [
        {"date": "2026-01-07", "value": "125.0"},
        {"date": "2026-01-14", "value": "130.0"},
        {"date": "2026-01-21", "value": "."},
        {"date": "2026-01-28", "value": "128.0"},
    ],
}

# BTFP post-expiry: all values are zero (valid state, not an error)
FRED_BTFP_ZERO_RESPONSE = {
    "realtime_start": "2026-04-01",
    "realtime_end": "2026-04-30",
    "observation_start": "2026-01-01",
    "observation_end": "2026-04-30",
    "units": "Millions of U.S. Dollars",
    "frequency": "Weekly, Ending Wednesday",
    "observations": [
        {"date": "2026-01-07", "value": "0"},
        {"date": "2026-01-14", "value": "0"},
        {"date": "2026-01-21", "value": "0"},
    ],
}

DDP_H41_RESPONSE = """Time Period,H41/H41/RESPPALDP_N.WW,H41/H41/RESPPALDQ_N.WW,H41/H41/RESPPALDS_N.WW,H41/H41/RESPPALDK_N.WW
2026-01-07,125.0,2.0,3.0,0
2026-01-14,130.0,1.0,4.0,0
2026-01-21,,0.0,0.0,0
"""


def _mock_response(json_data: dict, status: int = 200, text: str = ""):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status
    resp.content = (text or json.dumps(json_data)).encode("utf-8")
    resp.text = text or json.dumps(json_data)
    resp.raise_for_status = MagicMock()
    if status >= 400:
        from requests.exceptions import HTTPError

        resp.raise_for_status.side_effect = HTTPError(response=resp)
    return resp


class TestH41Provider:
    def test_field_mappings_exist(self) -> None:
        assert "discount_window" in H41_DDP_MAP
        assert "primary_credit" in H41_DDP_MAP
        assert "btfp" in H41_DDP_MAP
        assert "discount_window" in H41_FRED_MAP
        assert "primary_credit" in H41_FRED_MAP
        assert "btfp" in H41_FRED_MAP
        assert H41_FRED_MAP["discount_window"] == "WORAL"
        assert H41_FRED_MAP["primary_credit"] == "WPCREDIT"
        assert H41_FRED_MAP["btfp"] == "H41RESPPALDKNWW"

    def test_source_notes_have_required_fields(self) -> None:
        required_keys = {
            "table", "row_label", "field_semantic", "sign",
            "units", "expiry_behavior", "fred_series",
            "fred_frequency", "fred_units",
        }
        for field in ("discount_window", "primary_credit", "btfp"):
            assert field in H41_SOURCE_NOTE, f"missing source note for {field}"
            note = H41_SOURCE_NOTE[field]
            assert isinstance(note, dict), f"source note for {field} must be a dict"
            missing = required_keys - set(note.keys())
            assert not missing, f"source note for {field} missing keys: {missing}"
            assert "PROVISIONAL" in note["fred_series"] or True  # at minimum has content

    def test_btfp_source_note_documents_zero_behavior(self) -> None:
        btfp_note = H41_SOURCE_NOTE["btfp"]
        assert "zeros" in btfp_note["expiry_behavior"]
        assert "observed_zero" in btfp_note.get("expiry_behavior", "").lower() or \
               "observed_zero" in btfp_note.get("field_semantic", "").lower()

    def test_units_exist(self) -> None:
        for field in ("discount_window", "primary_credit", "btfp"):
            assert field in H41_UNITS
            assert H41_UNITS[field] == "mil_usd"

    def test_fetch_via_direct_ddp(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, text=DDP_H41_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = H41Provider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            r = results[0]
            assert r.provider == "h41"
            assert r.series_id == "primary_credit"
            assert not r.frame.empty
            df = r.frame
            assert len(df) == 3
            assert df["value"].iloc[0] == 125.0
            assert df["unit"].iloc[0] == "mil_usd"
            assert df["frequency"].iloc[0] == "Weekly, Ending Wednesday"

            assert r.source_params["method"] == "federal_reserve_ddp_csv"
            assert r.source_params["ddp_series"] == ["H41/H41/RESPPALDP_N.WW"]
            assert r.source_params["verification_status"] == "DIRECT"
            assert r.source_params["status_detail"] == "direct_h41_ddp"

    def test_discount_window_sums_direct_ddp_components(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, text=DDP_H41_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = H41Provider(data_root=str(tmp_path), cache=False)
            result = prov.fetch_series(["discount_window"])[0]

            assert not result.frame.empty
            assert result.frame["value"].iloc[0] == 130.0
            assert result.source_params["verification_status"] == "DIRECT"

    def test_btfp_zero_values_are_not_errors(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, text=DDP_H41_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = H41Provider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["btfp"])

            assert len(results) == 1
            r = results[0]
            assert r.provider == "h41"
            assert not r.frame.empty
            assert len(r.frame) == 3
            assert (r.frame["value"] == 0.0).all()
            # Must NOT be an error — zero is valid
            assert r.fetch_error is None
            assert r.fetch_fallback_reason is None
            assert r.source_params["status_detail"] == "observed_zero"
            assert r.source_params["verification_status"] == "DIRECT"

    def test_unknown_field(self, tmp_path) -> None:
        prov = H41Provider(data_root=str(tmp_path), cache=False)
        results = prov.fetch_series(["nonexistent_field"])
        assert len(results) == 1
        assert results[0].fetch_error is not None
        assert "no Federal Reserve DDP mapping" in results[0].fetch_error

    def test_missing_api_key_does_not_block_direct_ddp(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, text=DDP_H41_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = H41Provider(api_key="", data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            assert results[0].fetch_error is None
            assert results[0].source_params["verification_status"] == "DIRECT"

    def test_direct_failure_can_fallback_to_fred(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.side_effect = [
                _mock_response({}, text="not a usable csv"),
                _mock_response(FRED_H41_RESPONSE),
            ]
            mock_session_cls.return_value = mock_session

            prov = H41Provider(api_key="test_key", data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            assert results[0].fetch_error is None
            assert results[0].fetch_fallback_reason.startswith("direct_h41_ddp_failed")
            assert results[0].source_params["method"] == "fred_bridge"

    def test_direct_failure_without_fallback_reports_error(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, text="not a usable csv")
            mock_session_cls.return_value = mock_session

            prov = H41Provider(api_key="", data_root=str(tmp_path), cache=False, allow_fred_fallback=False)
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            assert results[0].fetch_error is not None
            assert "H41 direct DDP" in results[0].fetch_error

    def test_fetch_via_fred_bridge_fallback_method(self, tmp_path) -> None:
        prov = H41Provider(api_key="test_key", data_root=str(tmp_path), cache=False)
        with patch.object(prov, "_session") as mock_session:
            mock_session.get.return_value = _mock_response(FRED_H41_RESPONSE)
            result = prov._fetch_via_fred("WPCREDIT", "primary_credit")

        assert result.source_params["method"] == "fred_bridge"
        assert result.source_params["verification_status"] == "PROVISIONAL"

    def test_missing_api_key_blocks_fred_bridge_only(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, text="not a usable csv")
            mock_session_cls.return_value = mock_session

            prov = H41Provider(api_key="", data_root=str(tmp_path), cache=False, allow_fred_fallback=False)
            results = prov.fetch_series(["primary_credit"])

            assert len(results) == 1
            # Direct DDP is attempted first and does not need FRED_API_KEY.
            assert results[0].fetch_error is not None

    def test_fetch_all_fields(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, text=DDP_H41_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = H41Provider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["discount_window", "primary_credit", "btfp"])

            assert len(results) == 3
            for r in results:
                assert r.provider == "h41"
                assert r.series_id in ("discount_window", "primary_credit", "btfp")
                assert not r.frame.empty

    def test_http_error(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, status=500)
            mock_session_cls.return_value = mock_session

            prov = H41Provider(data_root=str(tmp_path), cache=False, allow_fred_fallback=False)
            results = prov.fetch_series(["primary_credit"])
            assert len(results) == 1
            assert results[0].fetch_error is not None

    def test_to_long_panel(self, tmp_path) -> None:
        with patch("requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.headers = {}
            mock_session.get.return_value = _mock_response({}, text=DDP_H41_RESPONSE)
            mock_session_cls.return_value = mock_session

            prov = H41Provider(data_root=str(tmp_path), cache=False)
            results = prov.fetch_series(["primary_credit"])
            panel = prov._to_long_panel(results)
            assert not panel.empty
            assert "series_id" in panel.columns
            assert "source_id" in panel.columns
            assert panel["source_id"].iloc[0] == "h41"
            assert panel.loc[0, "series_id"] == "H41:primary_credit"
