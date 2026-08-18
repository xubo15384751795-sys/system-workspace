from __future__ import annotations

import json

import httpx
import pytest

import harvester.http_gateway as gateway_module
from harvester.http_gateway import OwnedHTTPGateway
from harvester.providers.fred import FRED_MAX_RESPONSE_BYTES, FredProvider

FRED_OBS_RESPONSE = {
    "realtime_start": "2026-04-01",
    "realtime_end": "2026-04-30",
    "observation_start": "2026-01-01",
    "observation_end": "2026-04-30",
    "units": "Percent",
    "frequency": "Daily",
    "observations": [
        {"date": "2026-01-02", "value": "4.25"},
        {"date": "2026-01-03", "value": "4.25"},
        {"date": "2026-01-06", "value": "4.25"},
        {"date": "2026-01-07", "value": "4.26"},
        {"date": "2026-01-08", "value": "."},
    ],
}


def _mock_response(json_data: dict, status: int = 200, text: str = ""):
    content = (text or json.dumps(json_data)).encode("utf-8")
    return httpx.Response(status, content=content)


def _gateway(response: httpx.Response) -> OwnedHTTPGateway:
    return OwnedHTTPGateway(transport=httpx.MockTransport(lambda _request: response))


@pytest.fixture(autouse=True)
def _allow_fake_gateway_hosts(monkeypatch):
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)


class TestFredProvider:
    def test_default_gateway_has_bounded_large_series_budget(self, tmp_path) -> None:
        prov = FredProvider(api_key="test_key", data_root=str(tmp_path), cache=False)
        try:
            assert prov._gateway._max_response_bytes == FRED_MAX_RESPONSE_BYTES
            assert FRED_MAX_RESPONSE_BYTES == 4_000_000
        finally:
            prov._gateway.close()

    def test_parse_observations(self, tmp_path) -> None:
        with _gateway(_mock_response(FRED_OBS_RESPONSE)) as gateway:
            prov = FredProvider(api_key="test_key", data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["T10Y2Y"])

            assert len(results) == 1
            r = results[0]
            assert r.provider == "fred"
            assert r.series_id == "T10Y2Y"
            assert not r.frame.empty
            df = r.frame
            assert len(df) == 4  # 4 non-missing observations (one "." skipped)
            assert df["value"].iloc[0] == 4.25
            assert df["unit"].iloc[0] == "Percent"
            assert df["frequency"].iloc[0] == "Daily"

    def test_missing_api_key(self, tmp_path) -> None:
        prov = FredProvider(api_key="", data_root=str(tmp_path), cache=False)
        results = prov.fetch_series(["T10Y2Y"])
        assert len(results) == 1
        assert results[0].fetch_error is not None
        assert "FRED_API_KEY" in results[0].fetch_error
        assert results[0].frame.empty

    def test_http_error(self, tmp_path) -> None:
        with _gateway(_mock_response({}, status=500, text="Server Error")) as gateway:
            prov = FredProvider(api_key="test_key", data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["T10Y2Y"])

            assert len(results) == 1
            assert results[0].fetch_error is not None
            assert results[0].frame.empty

    def test_bad_request_invalid_series(self, tmp_path) -> None:
        with _gateway(_mock_response({}, status=400, text="Bad Request")) as gateway:
            prov = FredProvider(api_key="test_key", data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["NONEXISTENT"])

            assert len(results) == 1
            assert results[0].fetch_error is not None
            assert "400" in results[0].fetch_error

    def test_empty_observations(self, tmp_path) -> None:
        empty_response = dict(FRED_OBS_RESPONSE, observations=[])
        with _gateway(_mock_response(empty_response)) as gateway:
            prov = FredProvider(api_key="test_key", data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["T10Y2Y"])

            assert len(results) == 1
            assert results[0].fetch_error is not None
            assert "no observations" in results[0].fetch_error

    def test_to_long_panel(self, tmp_path) -> None:
        with _gateway(_mock_response(FRED_OBS_RESPONSE)) as gateway:
            prov = FredProvider(api_key="test_key", data_root=str(tmp_path), cache=False, gateway=gateway)
            results = prov.fetch_series(["T10Y2Y", "DFF"])

            assert len(results) == 2
            panel = prov._to_long_panel(results)
            assert not panel.empty
            assert "series_id" in panel.columns
            assert "source_id" in panel.columns
            assert "source_series_id" in panel.columns
            assert "value" in panel.columns
            assert "date" in panel.columns
            assert panel["source_id"].iloc[0] == "fred"
            assert panel.loc[0, "series_id"] in ("FRED:T10Y2Y", "FRED:DFF")
