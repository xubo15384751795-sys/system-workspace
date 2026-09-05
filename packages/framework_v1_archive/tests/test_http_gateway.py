from __future__ import annotations

import inspect

import httpx
import pytest
import src.data_access.http_gateway as gateway_module
from src.data_access.http_gateway import (
    EndpointSpec,
    GatewayError,
    GatewayPolicyError,
    GatewayResponseTooLarge,
    OwnedHTTPGateway,
)


def _endpoint() -> EndpointSpec:
    return EndpointSpec(
        provider="test_provider",
        endpoint_id="series",
        url="https://api.example.test/series",
        allowed_hosts=frozenset({"api.example.test"}),
    )


def test_gateway_fetches_registered_endpoint_with_fake_transport(monkeypatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    with OwnedHTTPGateway(
        {("test_provider", "series"): _endpoint()},
        transport=httpx.MockTransport(handler),
    ) as gateway:
        response = gateway.fetch("test_provider", "series", {"series_id": "DGS10"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls[0].url.path == "/series"
    assert calls[0].url.params["series_id"] == "DGS10"


def test_gateway_public_fetch_surface_is_provider_endpoint_and_params_only() -> None:
    assert list(inspect.signature(OwnedHTTPGateway.fetch).parameters) == [
        "self", "provider", "endpoint_id", "params"
    ]


def test_gateway_rejects_unknown_endpoint_before_transport(monkeypatch) -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    with OwnedHTTPGateway(transport=httpx.MockTransport(handler)) as gateway:
        with pytest.raises(GatewayPolicyError, match="unknown provider"):
            gateway.fetch("not_registered", "series", {})
    assert called is False


def test_gateway_disables_redirects_and_does_not_expose_location(monkeypatch) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://secret.example/?token=do-not-log"})

    with OwnedHTTPGateway(
        {("test_provider", "series"): _endpoint()},
        transport=httpx.MockTransport(handler),
    ) as gateway:
        with pytest.raises(GatewayPolicyError, match="redirects") as error:
            gateway.fetch("test_provider", "series", {"token": "do-not-log"})
    assert "do-not-log" not in str(error.value)
    assert "secret.example" not in str(error.value)


def test_gateway_enforces_response_size_without_returning_body(monkeypatch) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"0123456789")

    with OwnedHTTPGateway(
        {("test_provider", "series"): _endpoint()},
        transport=httpx.MockTransport(handler),
        max_response_bytes=4,
    ) as gateway:
        with pytest.raises(GatewayResponseTooLarge):
            gateway.fetch("test_provider", "series", {})


def test_gateway_wraps_transport_errors_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("token=do-not-log")

    with OwnedHTTPGateway(
        {("test_provider", "series"): _endpoint()},
        transport=httpx.MockTransport(handler),
    ) as gateway:
        with pytest.raises(GatewayError) as error:
            gateway.fetch("test_provider", "series", {"token": "do-not-log"})
    assert "do-not-log" not in str(error.value)


def test_pinned_network_backend_never_redials_original_hostname(monkeypatch) -> None:
    calls: list[str] = []

    class FakeBackend:
        def connect_tcp(self, host, port, *, timeout, local_address, socket_options):
            calls.append(host)
            return object()

    backend = gateway_module._PinnedNetworkBackend(
        "api.example.test", ("203.0.113.10", "2001:db8::10")
    )
    backend._backend = FakeBackend()

    result = backend.connect_tcp(
        "api.example.test",
        443,
        timeout=1.0,
        local_address=None,
        socket_options=None,
    )

    assert result is not None
    assert calls == ["203.0.113.10"]

    with pytest.raises(gateway_module.httpcore.ConnectError, match="host mismatch"):
        backend.connect_tcp("other.example.test", 443)


def test_default_gateway_uses_single_resolved_address_snapshot(monkeypatch) -> None:
    resolved: list[str] = []
    constructed: list[tuple[str, tuple[str, ...]]] = []

    class FakePinnedTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"ok", request=request)

        def close(self) -> None:
            return None

    def resolve(url: str) -> tuple[str, ...]:
        resolved.append(url)
        return ("203.0.113.10",)

    def make_transport(host: str, addresses, **_kwargs):
        constructed.append((host, tuple(addresses)))
        return FakePinnedTransport()

    monkeypatch.setattr(gateway_module, "resolve_outbound_url", resolve)
    monkeypatch.setattr(gateway_module, "_PinnedHTTPTransport", make_transport)
    with OwnedHTTPGateway({("test_provider", "series"): _endpoint()}) as gateway:
        response = gateway.fetch("test_provider", "series", {"series_id": "DGS10"})

    assert response.content == b"ok"
    assert len(resolved) == 1
    assert constructed == [("api.example.test", ("203.0.113.10",))]
