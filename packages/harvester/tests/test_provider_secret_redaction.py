from __future__ import annotations

import logging

import harvester.http_gateway as gateway_module
import httpx
from harvester.http_gateway import OwnedHTTPGateway
from harvester.providers.fred import FredProvider
from harvester.providers.h41 import H41Provider

SECRET = "provider-secret-not-for-logs"


def _failing_gateway(captured: list[str]) -> OwnedHTTPGateway:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        raise httpx.ConnectError(f"api_key={SECRET}")

    return OwnedHTTPGateway(transport=httpx.MockTransport(handler))


def test_fred_secret_stays_in_outbound_request_only(monkeypatch, caplog, tmp_path) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    captured: list[str] = []
    caplog.set_level(logging.WARNING)

    with _failing_gateway(captured) as gateway:
        result = FredProvider(
            api_key=SECRET,
            data_root=str(tmp_path),
            cache=False,
            gateway=gateway,
        ).fetch_series(["DGS10"])[0]

    assert captured and SECRET in captured[0]
    assert SECRET not in (result.fetch_error or "")
    assert SECRET not in result.source_url
    assert SECRET not in str(result.source_params)
    assert SECRET not in caplog.text


def test_h41_fred_fallback_secret_stays_out_of_error_chain(monkeypatch, caplog, tmp_path) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    captured: list[str] = []
    caplog.set_level(logging.WARNING)

    with _failing_gateway(captured) as gateway:
        result = H41Provider(
            api_key=SECRET,
            data_root=str(tmp_path),
            cache=False,
            gateway=gateway,
        ).fetch_series(["primary_credit"])[0]

    assert len(captured) == 2
    assert SECRET in captured[1]
    assert SECRET not in (result.fetch_error or "")
    assert SECRET not in result.source_url
    assert SECRET not in str(result.source_params)
    assert SECRET not in str(result.fetch_fallback_reason or "")
    assert SECRET not in caplog.text
