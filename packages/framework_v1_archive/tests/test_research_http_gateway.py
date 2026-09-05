"""Research-only HTTP paths use the owned endpoint gateway."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import src.data_access.http_gateway as gateway_module
from src.benchmarks import historical_replay
from src.data_access.http_gateway import (
    EndpointSpec,
    GatewayPolicyError,
    OwnedHTTPGateway,
)
from src.research_corpus.providers.brevan_howard import BrevanHowardProvider

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_gateway_renders_bounded_research_path_and_query(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"document")

    endpoint = EndpointSpec(
        provider="research",
        endpoint_id="document",
        url="https://docs.example.test/{path}",
        allowed_hosts=frozenset({"docs.example.test"}),
        path_parameters=frozenset({"path"}),
    )
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    with OwnedHTTPGateway(
        {("research", "document"): endpoint},
        transport=httpx.MockTransport(handler),
    ) as gateway:
        response = gateway.fetch(
            "research",
            "document",
            params={"download": "1", "path": "reports/2025 report.pdf"},
        )

    assert response.content == b"document"
    assert seen[0].url.host == "docs.example.test"
    assert "/reports/2025%20report.pdf" in str(seen[0].url)
    assert seen[0].url.params["download"] == "1"


def test_brevan_provider_rejects_unregistered_host(monkeypatch) -> None:
    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    with OwnedHTTPGateway(transport=httpx.MockTransport(lambda _request: httpx.Response(200))) as gateway:
        provider = BrevanHowardProvider(gateway=gateway)
        with pytest.raises(GatewayPolicyError, match="registered endpoint"):
            provider._fetch_bytes("https://untrusted.example/document.pdf")


def test_brevan_provider_fetches_through_registered_endpoint(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"research bytes")

    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    with OwnedHTTPGateway(transport=httpx.MockTransport(handler)) as gateway:
        provider = BrevanHowardProvider(gateway=gateway)
        content = provider._fetch_bytes(
            "https://www.bhmacro.com/reporting/2025 report.pdf?download=1"
        )

    assert content == b"research bytes"
    assert seen[0].url.host == "www.bhmacro.com"
    assert "/reporting/2025%20report.pdf" in str(seen[0].url)
    assert seen[0].url.params["download"] == "1"


def test_historical_replay_fetches_fred_via_endpoint_id(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"observation_date,VIXCLS\n2025-01-01,20\n")

    monkeypatch.setattr(gateway_module, "validate_outbound_url", lambda url: url)
    fake_gateway = OwnedHTTPGateway(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(historical_replay, "OwnedHTTPGateway", lambda **_kwargs: fake_gateway)

    csv_text = historical_replay._download_fred_graph_csv("VIXCLS", timeout_sec=5)

    assert "observation_date,VIXCLS" in csv_text
    assert seen[0].url.host == "fred.stlouisfed.org"
    assert seen[0].url.params["id"] == "VIXCLS"


def test_research_sources_have_no_raw_http_fallback() -> None:
    sources = (
        PACKAGE_ROOT / "src/benchmarks/historical_replay.py",
        PACKAGE_ROOT / "src/research_corpus/providers/brevan_howard.py",
    )
    for path in sources:
        source = path.read_text(encoding="utf-8")
        assert "urlopen" not in source
        assert "subprocess" not in source
        assert "curl" not in source
