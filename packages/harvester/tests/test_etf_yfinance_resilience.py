"""Failure-injection tests for the yfinance provider guard."""
from __future__ import annotations

import sys
import types
import json
from pathlib import Path

import pandas as pd

from harvester.providers.etf_yfinance import EtfYfinanceProvider


def test_rate_limit_opens_persistent_cooldown_and_prevents_second_call(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[object] = []

    class TooManyRequests(Exception):
        pass

    def download(*_args, **_kwargs):
        calls.append(1)
        raise TooManyRequests("Too Many Requests. Rate limited. Try after a while.")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=download))
    monkeypatch.setenv("YFINANCE_COOLDOWN_S", "600")

    provider = EtfYfinanceProvider(
        tickers={ticker: ticker for ticker in ("SPY", "QQQ", "HYG", "LQD")},
        data_root=str(tmp_path),
        cache=False,
    )
    first = provider.fetch_series(["SPY", "QQQ", "HYG", "LQD"])
    second = EtfYfinanceProvider(
        tickers={"SPY": "SPY"},
        data_root=str(tmp_path),
        cache=False,
    ).fetch_series(["SPY"])

    assert len(calls) == 1
    assert all(item.fetch_fallback_reason == "provider_cooldown" for item in first)
    assert second[0].fetch_fallback_reason == "provider_cooldown"
    state = (tmp_path / "provider_state" / "yfinance.json").read_text(encoding="utf-8")
    assert '"state": "cooldown"' in state


def test_empty_batch_does_not_fan_out_to_individual_tickers(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[object] = []

    def download(*_args, **_kwargs):
        calls.append(1)
        return pd.DataFrame()

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=download))
    provider = EtfYfinanceProvider(
        tickers={ticker: ticker for ticker in ("SPY", "QQQ", "HYG", "LQD", "TLT")},
        data_root=str(tmp_path),
        cache=False,
    )

    results = provider.fetch_series(["SPY", "QQQ", "HYG", "LQD", "TLT"])

    assert len(calls) == 1
    assert len(results) == 5
    assert all(item.fetch_fallback_reason == "batch_empty_no_fanout" for item in results)


def test_recent_raw_cache_is_reused_before_network_call(
    tmp_path: Path, monkeypatch
) -> None:
    raw_dir = tmp_path / "raw" / "yfinance"
    raw_dir.mkdir(parents=True)
    (raw_dir / "HYG_raw.json").write_text(
        json.dumps(
            [
                {
                    "date": "2026-08-12T00:00:00.000Z",
                    "value": 78.5,
                    "open": 78.0,
                    "high": 79.0,
                    "low": 77.5,
                    "volume": 100.0,
                    "unit": "USD",
                    "frequency": "daily",
                }
            ]
        ),
        encoding="utf-8",
    )

    def network_must_not_run(*_args, **_kwargs):
        raise AssertionError("recent shared ETF cache should avoid another provider call")

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        types.SimpleNamespace(download=network_must_not_run),
    )
    provider = EtfYfinanceProvider(
        tickers={"HYG": "HYG"},
        data_root=str(tmp_path),
        cache=True,
    )

    result = provider.fetch_series(["HYG"])[0]

    assert result.fetch_error is None
    assert result.frame.iloc[0]["value"] == 78.5


def test_yfinance_backoff_is_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YFINANCE_COOLDOWN_S", "10")
    monkeypatch.setenv("YFINANCE_BACKOFF_MAX_S", "25")
    provider = EtfYfinanceProvider(
        tickers={"SPY": "SPY"},
        data_root=str(tmp_path),
        cache=False,
    )

    provider._gate.mark_rate_limited("first")
    first = json.loads(
        (tmp_path / "provider_state" / "yfinance.json").read_text(encoding="utf-8")
    )
    provider._gate.mark_rate_limited("second")
    second = json.loads(
        (tmp_path / "provider_state" / "yfinance.json").read_text(encoding="utf-8")
    )

    assert first["backoff_s"] == 10
    assert second["backoff_s"] == 20
