from __future__ import annotations

import inspect

import harvester.http_gateway as gateway_module
import httpx
import pytest
from harvester.http_gateway import (
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


def test_gateway_preserves_registered_query_when_no_runtime_params(monkeypatch) -> None:
    calls: list[httpx.Request] = []
    endpoint = EndpointSpec(
        provider="test_provider",
        endpoint_id="cftc",
        url="https://api.example.test/resource.json?$select=foo&$limit=10",
        allowed_hosts=frozenset({"api.example.test"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    with OwnedHTTPGateway(
        {("test_provider", "cftc"): endpoint},
        transport=httpx.MockTransport(handler),
    ) as gateway:
        gateway.fetch("test_provider", "cftc")

    assert calls[0].url.params["$select"] == "foo"
    assert calls[0].url.params["$limit"] == "10"


def test_gateway_proxy_requires_explicit_credential_free_opt_in(monkeypatch) -> None:
    endpoint = EndpointSpec(
        provider="test_provider",
        endpoint_id="series",
        url="https://api.example.test/series",
        allowed_hosts=frozenset({"api.example.test"}),
        proxy_env_var="TEST_PROVIDER_PROXY",
    )

    monkeypatch.setenv("TEST_PROVIDER_PROXY", "http://127.0.0.1:7897")
    assert gateway_module._configured_proxy_url(endpoint) == "http://127.0.0.1:7897"

    monkeypatch.setenv("TEST_PROVIDER_PROXY", "http://user:secret@127.0.0.1:7897")
    with pytest.raises(GatewayPolicyError, match="proxy"):
        gateway_module._configured_proxy_url(endpoint)


def test_gateway_public_fetch_surface_is_provider_endpoint_and_params_only() -> None:
    assert list(inspect.signature(OwnedHTTPGateway.fetch).parameters) == [
        "self", "provider", "endpoint_id", "params"
    ]


def test_gateway_rejects_unknown_endpoint_before_transport() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    with OwnedHTTPGateway(transport=httpx.MockTransport(handler)) as gateway:
        with pytest.raises(GatewayPolicyError, match="unknown provider"):
            gateway.fetch("not_registered", "series", {})
    assert called is False


def test_gateway_disables_redirects_and_does_not_expose_query_values(monkeypatch) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://secret.example/?token=hidden"})

    with OwnedHTTPGateway(
        {("test_provider", "series"): _endpoint()},
        transport=httpx.MockTransport(handler),
    ) as gateway:
        with pytest.raises(GatewayPolicyError, match="redirects") as error:
            gateway.fetch("test_provider", "series", {"token": "hidden"})
    assert "hidden" not in str(error.value)
    assert "secret.example" not in str(error.value)


def test_gateway_renders_only_bounded_registered_path_parameters(monkeypatch) -> None:
    seen: list[str] = []
    endpoint = EndpointSpec(
        provider="test_provider",
        endpoint_id="companyconcept",
        url="https://api.example.test/CIK{cik}/us-gaap/{tag}.json",
        allowed_hosts=frozenset({"api.example.test"}),
        path_parameters=frozenset({"cik", "tag"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    with OwnedHTTPGateway(
        {("test_provider", "companyconcept"): endpoint},
        transport=httpx.MockTransport(handler),
    ) as gateway:
        gateway.fetch(
            "test_provider",
            "companyconcept",
            {"cik": "0000072971", "tag": "Assets"},
        )
        with pytest.raises(GatewayPolicyError, match="unsafe"):
            gateway.fetch(
                "test_provider",
                "companyconcept",
                {"cik": "0000072971/../../x", "tag": "Assets"},
            )

    assert "/CIK0000072971/us-gaap/Assets.json" in seen[0]


def test_harvester_provider_sources_have_no_direct_http_sinks() -> None:
    from pathlib import Path

    source_root = Path(__file__).resolve().parents[1] / "src" / "harvester"
    banned = (
        "import requests",
        "requests.Session",
        "requests.get",
        "requests.post",
        "requests.request",
        "httpx.get",
        "httpx.post",
        "httpx.request",
        "urllib.request",
        "aiohttp",
        "urlopen(",
    )
    violations = [
        f"{path}:{line_no}: {needle}"
        for path in source_root.rglob("*.py")
        if path.name != "http_gateway.py"
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for needle in banned
        if needle in line
    ]
    assert not violations, "direct provider HTTP sinks found: " + "; ".join(violations)


def test_gateway_enforces_response_size(monkeypatch) -> None:
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


def test_gateway_enforces_total_response_timeout(monkeypatch) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    clock = iter((0.0, 2.0))
    monkeypatch.setattr(gateway_module.time, "monotonic", lambda: next(clock, 2.0))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"slow")

    with OwnedHTTPGateway(
        {("test_provider", "series"): _endpoint()},
        transport=httpx.MockTransport(handler),
        timeout_sec=1,
    ) as gateway:
        with pytest.raises(GatewayError, match="provider transport failed"):
            gateway.fetch("test_provider", "series", {})


def test_gateway_wraps_transport_errors_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("token=hidden")

    with OwnedHTTPGateway(
        {("test_provider", "series"): _endpoint()},
        transport=httpx.MockTransport(handler),
    ) as gateway:
        with pytest.raises(GatewayError) as error:
            gateway.fetch("test_provider", "series", {"token": "hidden"})
    assert "hidden" not in str(error.value)


def test_pinned_network_backend_never_redials_original_hostname() -> None:
    calls: list[str] = []

    class FakeBackend:
        def connect_tcp(self, host, port, *, timeout, local_address, socket_options):
            calls.append(host)
            return object()

    backend = gateway_module._PinnedNetworkBackend(
        "api.example.test", ("203.0.113.10", "2001:4860:4860::8888")
    )
    backend._backend = FakeBackend()

    result = backend.connect_tcp("api.example.test", 443)

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

    def make_transport(expected_host: str, addresses, **_kwargs):
        constructed.append((expected_host, tuple(addresses)))
        return FakePinnedTransport()

    monkeypatch.setattr(gateway_module, "resolve_outbound_url", resolve)
    monkeypatch.setattr(gateway_module, "_PinnedHTTPTransport", make_transport)
    with OwnedHTTPGateway({("test_provider", "series"): _endpoint()}) as gateway:
        response = gateway.fetch("test_provider", "series", {"series_id": "DGS10"})

    assert response.content == b"ok"
    assert len(resolved) == 1
    assert constructed == [("api.example.test", ("203.0.113.10",))]
