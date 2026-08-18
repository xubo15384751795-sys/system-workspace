from __future__ import annotations

import httpx
import pytest

import harvester.http_gateway as gateway_module
from harvester.http_gateway import OwnedHTTPGateway
from harvester.providers import build_provider
from harvester.providers.cboe_direct import CboeDirectProvider


def _gateway(response: httpx.Response) -> OwnedHTTPGateway:
    return OwnedHTTPGateway(transport=httpx.MockTransport(lambda _request: response))


@pytest.fixture(autouse=True)
def _allow_fake_gateway_hosts(monkeypatch):
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)


def test_cboe_direct_parses_eod_csv(tmp_path) -> None:
    response = httpx.Response(200, content=b"DATE,OPEN,HIGH,LOW,CLOSE\n05/06/2026,1,2,0.5,17.39\n")
    with _gateway(response) as gateway:
        provider = CboeDirectProvider(data_root=tmp_path, cache=False, gateway=gateway)
        result = provider.fetch_series(["VIX3M"])[0]

    assert result.fetch_error is None
    assert result.provider == "cboe"
    assert result.series_id == "VIX3M"
    assert result.frame["series_id"].tolist() == ["CBOE:VIX3M"]
    assert result.frame["value"].tolist() == [17.39]
    assert result.source_params["endpoint_family"] == "daily_prices_csv"


def test_cboe_direct_maps_move_slot_to_current_vxtlt_source(tmp_path) -> None:
    response = httpx.Response(200, content=b"DATE,VXTLT\n05/05/2026,13.03\n05/06/2026,12.22\n")
    with _gateway(response) as gateway:
        provider = CboeDirectProvider(data_root=tmp_path, cache=False, gateway=gateway)
        result = provider.fetch_series(["MOVE"])[0]

    assert result.fetch_error is None
    assert result.series_id == "MOVE"
    assert result.frame["series_id"].unique().tolist() == ["CBOE:MOVE"]
    assert result.frame["source_series_id"].unique().tolist() == ["VXTLT"]
    assert result.frame["value"].tolist() == [13.03, 12.22]


def test_cboe_direct_parses_delayed_quote_json(tmp_path) -> None:
    payload = {
        "timestamp": "2026-05-07 03:43:58",
        "data": {
            "current_price": 17.39,
            "last_trade_time": "2026-05-06T16:15:01",
        },
        "symbol": "_VIX",
    }
    with _gateway(httpx.Response(200, json=payload)) as gateway:
        provider = CboeDirectProvider(data_root=tmp_path, cache=False, gateway=gateway)
        result = provider.fetch_series(["VIXCLS"])[0]

    assert result.fetch_error is None
    assert result.provider == "cboe"
    assert result.series_id == "VIXCLS"
    assert result.frame["source_series_id"].tolist() == ["VIX"]
    assert result.frame["frequency"].tolist() == ["intraday_delayed"]
    assert result.frame["value"].tolist() == [17.39]
    assert result.source_params["endpoint_family"] == "delayed_quotes_json"


def test_build_provider_supports_cboe_direct(tmp_path) -> None:
    provider = build_provider("cboe_direct", data_root=tmp_path, cache=False)

    assert isinstance(provider, CboeDirectProvider)
