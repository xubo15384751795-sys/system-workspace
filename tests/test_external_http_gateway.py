from __future__ import annotations

import httpx
import pytest

import system_runtime.external_http as gateway_module
from system_runtime.external_http import (
    ExternalEndpointSpec,
    ExternalGatewayError,
    ExternalGatewayPolicyError,
    ExternalGatewayResponseTooLarge,
    OwnedExternalHTTPGateway,
    resolve_external_url,
)


def _endpoint() -> ExternalEndpointSpec:
    return ExternalEndpointSpec(
        endpoint_id="sink",
        url="https://sink.example.test/events",
        allowed_hosts=frozenset({"sink.example.test"}),
    )


def test_external_gateway_posts_only_to_registered_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, content=b"accepted")

    with OwnedExternalHTTPGateway(
        {"sink": _endpoint()}, transport=httpx.MockTransport(handler)
    ) as gateway:
        response = gateway.post(
            "sink",
            b'{"message":"safe"}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 202
    assert seen[0].url == "https://sink.example.test/events"
    assert seen[0].content == b'{"message":"safe"}'


def test_external_endpoint_rejects_non_https_query_and_unallowlisted_host() -> None:
    with pytest.raises(ExternalGatewayPolicyError):
        ExternalEndpointSpec("sink", "http://sink.example.test/events", frozenset({"sink.example.test"}))
    with pytest.raises(ExternalGatewayPolicyError):
        ExternalEndpointSpec(
            "sink",
            "https://sink.example.test/events?token=secret",
            frozenset({"sink.example.test"}),
        )
    with pytest.raises(ExternalGatewayPolicyError):
        ExternalEndpointSpec("sink", "https://other.example.test/events", frozenset({"sink.example.test"}))


def test_external_gateway_blocks_redirect_and_response_overflow() -> None:
    def redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://secret.example/"})

    with OwnedExternalHTTPGateway(
        {"sink": _endpoint()}, transport=httpx.MockTransport(redirect)
    ) as gateway:
        with pytest.raises(ExternalGatewayPolicyError, match="redirects"):
            gateway.post("sink", b"x")

    def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"0123456789")

    with OwnedExternalHTTPGateway(
        {"sink": _endpoint()},
        transport=httpx.MockTransport(oversized),
        max_response_bytes=4,
    ) as gateway:
        with pytest.raises(ExternalGatewayResponseTooLarge):
            gateway.post("sink", b"x")


def test_external_gateway_redacts_transport_error() -> None:
    def failing(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("token=secret")

    with OwnedExternalHTTPGateway(
        {"sink": _endpoint()}, transport=httpx.MockTransport(failing)
    ) as gateway:
        with pytest.raises(ExternalGatewayError) as error:
            gateway.post("sink", b"x")
    assert "secret" not in str(error.value)


def test_default_external_gateway_uses_one_dns_snapshot(monkeypatch) -> None:
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

    def make_transport(host: str, addresses):
        constructed.append((host, tuple(addresses)))
        return FakePinnedTransport()

    monkeypatch.setattr(gateway_module, "resolve_external_url", resolve)
    monkeypatch.setattr(gateway_module, "_PinnedHTTPTransport", make_transport)
    with OwnedExternalHTTPGateway({"sink": _endpoint()}) as gateway:
        response = gateway.post("sink", b"x")

    assert response.content == b"ok"
    assert resolved == ["https://sink.example.test/events"]
    assert constructed == [("sink.example.test", ("203.0.113.10",))]


def test_pinned_backend_dials_snapshot_addresses_not_hostname() -> None:
    calls: list[str] = []

    class FakeBackend:
        def connect_tcp(self, host, port, *, timeout, local_address, socket_options):
            calls.append(host)
            return object()

    backend = gateway_module._PinnedNetworkBackend(
        "sink.example.test", ("203.0.113.10", "2001:4860:4860::8888")
    )
    backend._backend = FakeBackend()

    assert backend.connect_tcp("sink.example.test", 443) is not None
    assert calls == ["203.0.113.10"]
    with pytest.raises(gateway_module.httpcore.ConnectError, match="host mismatch"):
        backend.connect_tcp("other.example.test", 443)


def test_resolver_rejects_private_dns_and_deduplicates_public_addresses(monkeypatch) -> None:
    with monkeypatch.context() as context:
        context.setattr(
            gateway_module.socket,
            "getaddrinfo",
            lambda *_args, **_kwargs: [
                ("AF_INET", "SOCK_STREAM", "IPPROTO_TCP", "", ("10.0.0.2", 443))
            ],
        )
        with pytest.raises(ExternalGatewayPolicyError):
            resolve_external_url("https://sink.example.test/events")

    monkeypatch.setattr(
        gateway_module.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            ("AF_INET", "SOCK_STREAM", "IPPROTO_TCP", "", ("93.184.216.34", 443)),
            ("AF_INET", "SOCK_STREAM", "IPPROTO_TCP", "", ("93.184.216.34", 443)),
        ],
    )
    assert resolve_external_url("https://sink.example.test/events") == ("93.184.216.34",)


def test_non_data_sinks_do_not_own_raw_http_sinks() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sources = (
        root / "system_runtime" / "observability.py",
        root / "scripts" / "_notify.py",
        root / "packages/workbench/src/nlp/extraction/llm_extractor.py",
    )
    forbidden = ("urlopen(", "urllib.request", "requests.get(", "httpx.post(")
    violations = [
        f"{path}:{needle}"
        for path in sources
        for needle in forbidden
        if needle in path.read_text(encoding="utf-8")
    ]
    assert not violations, "non-data sink bypasses owned external gateway: " + "; ".join(violations)


def test_data_and_non_data_gateways_have_separate_transport_ownership() -> None:
    """Data acquisition and notification/LLM egress must not share a gateway."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data_sources = (
        root / "packages/framework/src/data_access/http_gateway.py",
        root / "packages/harvester/src/harvester/http_gateway.py",
    )
    non_data_sources = (
        root / "system_runtime/external_http.py",
        root / "packages/workbench/src/workbench/external_http.py",
    )
    data_text = "\n".join(path.read_text(encoding="utf-8") for path in data_sources)
    non_data_text = "\n".join(path.read_text(encoding="utf-8") for path in non_data_sources)
    assert "OwnedExternalHTTPGateway" not in data_text
    assert "OwnedHTTPGateway" not in non_data_text
    assert "system_runtime.external_http" not in data_text
    assert "data_access.http_gateway" not in non_data_text
