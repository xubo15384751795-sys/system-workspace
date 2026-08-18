"""Contract and fault-injection tests for the ETF provider chain."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from harvester.providers.base import OfficialProvider, ProviderResult
from harvester.providers.etf_market_data import (
    EtfProviderChain,
    MassiveEodProvider,
    TiingoEodProvider,
    _attempt_failure_class,
)


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        import json

        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")
        self.text = self.content.decode("utf-8")

    def json(self) -> Any:
        import json

        return json.loads(self.content)


class _Gateway:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def fetch(self, provider: str, endpoint_id: str, params: dict[str, object]) -> _Response:
        self.calls.append((provider, endpoint_id, dict(params)))
        return self.response


def _tiingo_rows() -> list[dict[str, Any]]:
    return [
        {
            "date": "2026-08-12T00:00:00.000Z",
            "open": 100,
            "high": 102,
            "low": 99,
            "close": 101,
            "volume": 1000,
            "adjOpen": 100,
            "adjHigh": 102,
            "adjLow": 99,
            "adjClose": 101,
            "adjVolume": 1000,
        }
    ]


def test_tiingo_normalizes_adjusted_eod_rows(tmp_path: Path) -> None:
    gateway = _Gateway(_Response(200, _tiingo_rows()))
    provider = TiingoEodProvider(
        api_key="secret-do-not-log",
        data_root=tmp_path,
        cache=False,
        gateway=gateway,  # type: ignore[arg-type]
    )

    result = provider.fetch_series(["SPY"])[0]

    assert result.provider == "tiingo"
    assert result.frame.iloc[0]["value"] == 101
    assert gateway.calls[0][0:2] == ("tiingo", "daily_prices")
    assert "secret-do-not-log" not in str(result.source_params)


def test_attempt_failure_class_is_stable_for_downstream_admission() -> None:
    cases = {
        "rate_limited": "RATE_LIMIT",
        "provider_cooldown": "PROVIDER_DOWN",
        "transport_error": "NETWORK",
        "empty": "NO_DATA",
        "schema_changed": "SCHEMA_CHANGED",
        "parser_error": "PARSER",
        "permission_denied": "PERMISSION",
        "unclassified_reason": "UNKNOWN",
    }
    for reason, expected in cases.items():
        assert _attempt_failure_class(reason=reason, error="", outcome="failed") == expected
    assert _attempt_failure_class(reason="anything", error="", outcome="success") == "NONE"


def test_massive_normalizes_aggregate_rows(tmp_path: Path) -> None:
    gateway = _Gateway(
        _Response(
            200,
            {
                "adjusted": True,
                "results": [
                    {"t": 1786492800000, "o": 100, "h": 102, "l": 99, "c": 101, "v": 1000}
                ],
            },
        )
    )
    provider = MassiveEodProvider(
        api_key="secret-do-not-log",
        data_root=tmp_path,
        cache=False,
        gateway=gateway,  # type: ignore[arg-type]
    )

    result = provider.fetch_series(["SPY"])[0]

    assert result.provider == "massive"
    assert result.frame.iloc[0]["value"] == 101
    assert gateway.calls[0][0:2] == ("massive", "daily_aggs")
    assert gateway.calls[0][2]["multiplier"] == "1"
    assert gateway.calls[0][2]["timespan"] == "day"


class _FailingProvider(OfficialProvider):
    source_id = "tiingo"

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        return [
            self._build_error_result(symbol, "fixture 429", "rate_limited")
            for symbol in series_ids
        ]


class _WorkingProvider(OfficialProvider):
    source_id = "massive"

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-08-12"]),
                "value": [101.0],
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "volume": [1000.0],
            }
        )
        return [ProviderResult(provider=self.source_id, series_id=symbol, frame=frame.copy()) for symbol in series_ids]


def test_chain_moves_to_massive_after_tiingo_throttle(tmp_path: Path) -> None:
    chain = EtfProviderChain(
        tickers={"SPY": "SPY"},
        data_root=tmp_path,
        provider_order=("tiingo", "massive"),
        provider_instances={
            "tiingo": _FailingProvider(data_root=tmp_path),
            "massive": _WorkingProvider(data_root=tmp_path),
        },
    )

    result = chain.fetch_series(["SPY"])[0]

    assert result.provider == "massive"
    assert result.fetch_fallback_reason == "provider_chain_fallback"
    assert result.source_params["fallback_from"] == ["tiingo"]
    attempts = result.source_params["provider_attempts"]
    assert [item["provider"] for item in attempts] == ["tiingo", "massive"]
    assert attempts[0]["reason"] == "rate_limited"
    assert attempts[0]["failure_class"] == "RATE_LIMIT"
    assert attempts[1]["outcome"] == "success"
    assert attempts[1]["failure_class"] == "NONE"
    assert attempts[0]["provider_attempt_id"].startswith("att_")
    assert attempts[1]["source_tier"] == 2


def test_chain_falls_back_to_yfinance_after_missing_authenticated_sources(
    tmp_path: Path,
) -> None:
    """The no-key last resort must remain a real, provenance-bearing route."""

    class _MissingKeyProvider(OfficialProvider):
        def __init__(self, source_id: str, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.source_id = source_id

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            return [
                self._build_error_result(
                    symbol,
                    f"missing {self.source_id} API key",
                    "missing_api_key",
                )
                for symbol in series_ids
            ]

    class _YFinanceFixture(_WorkingProvider):
        source_id = "yfinance"

    chain = EtfProviderChain(
        tickers={"JNK": "JNK"},
        data_root=tmp_path,
        provider_order=("tiingo", "massive", "yfinance"),
        provider_instances={
            "tiingo": _MissingKeyProvider("tiingo", data_root=tmp_path),
            "massive": _MissingKeyProvider("massive", data_root=tmp_path),
            "yfinance": _YFinanceFixture(data_root=tmp_path),
        },
    )

    result = chain.fetch_series(["JNK"])[0]

    assert result.provider == "yfinance"
    assert result.fetch_fallback_reason == "provider_chain_fallback"
    attempts = result.source_params["provider_attempts"]
    assert [item["provider"] for item in attempts] == ["tiingo", "massive", "yfinance"]
    assert [item["failure_class"] for item in attempts] == ["PERMISSION", "PERMISSION", "NONE"]
    assert attempts[-1]["outcome"] == "success"


def test_chain_records_primary_success_attempt(tmp_path: Path) -> None:
    class _HealthyProvider(OfficialProvider):
        source_id = "tiingo"

        def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-08-12"]),
                    "value": [101.0],
                    "open": [100.0],
                    "high": [102.0],
                    "low": [99.0],
                    "volume": [1000.0],
                }
            )
            return [ProviderResult(self.source_id, symbol, frame.copy()) for symbol in series_ids]

    chain = EtfProviderChain(
        tickers={"SPY": "SPY"},
        data_root=tmp_path,
        provider_order=("tiingo",),
        provider_instances={"tiingo": _HealthyProvider(data_root=tmp_path)},
    )

    result = chain.fetch_series(["SPY"])[0]

    attempts = result.source_params["provider_attempts"]
    assert len(attempts) == 1
    assert attempts[0]["provider"] == "tiingo"
    assert attempts[0]["outcome"] == "success"
    assert attempts[0]["retryable"] is False
    assert attempts[0]["failure_class"] == "NONE"


def test_authenticated_provider_429_opens_persistent_cooldown(tmp_path: Path) -> None:
    gateway = _Gateway(_Response(429, {"message": "Too Many Requests"}))
    provider = TiingoEodProvider(
        api_key="secret-do-not-log",
        data_root=tmp_path,
        cache=False,
        gateway=gateway,  # type: ignore[arg-type]
    )

    first = provider.fetch_series(["SPY", "QQQ"])
    second = provider.fetch_series(["TLT"])

    assert first[0].fetch_fallback_reason == "rate_limited"
    assert first[1].fetch_fallback_reason == "provider_cooldown"
    assert second[0].fetch_fallback_reason == "provider_cooldown"
    assert len(gateway.calls) == 1


def test_authenticated_provider_backoff_is_bounded_and_resets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TIINGO_COOLDOWN_S", "10")
    monkeypatch.setenv("TIINGO_BACKOFF_MAX_S", "25")
    provider = TiingoEodProvider(api_key="fixture", data_root=tmp_path, cache=False)

    provider._gate.mark_rate_limited("first")
    first = json.loads(
        (tmp_path / "provider_state" / "tiingo.json").read_text(encoding="utf-8")
    )
    provider._gate.mark_rate_limited("second")
    second = json.loads(
        (tmp_path / "provider_state" / "tiingo.json").read_text(encoding="utf-8")
    )
    provider._gate.mark_rate_limited("third")
    third = json.loads(
        (tmp_path / "provider_state" / "tiingo.json").read_text(encoding="utf-8")
    )

    assert first["backoff_s"] == 10
    assert second["backoff_s"] == 20
    assert third["backoff_s"] == 25
    provider._gate.mark_success()
    reset = json.loads(
        (tmp_path / "provider_state" / "tiingo.json").read_text(encoding="utf-8")
    )
    assert reset["failure_count"] == 0
    assert reset["cooldown_until"] == 0
