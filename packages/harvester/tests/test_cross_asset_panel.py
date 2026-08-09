"""Tests for cross-asset panel Harvester dataset staging."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from harvester.cross_asset_panel import (
    PANEL_COLUMNS,
    build_cross_asset_panel,
    compute_derived_columns,
    stage_cross_asset_panel,
)


def test_compute_derived_columns_adds_returns(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "symbol": ["SPY", "SPY", "SPY"],
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 102.0, 101.0],
            "volume": [1_000, 1_100, 1_200],
        }
    )
    derived = compute_derived_columns(frame)
    assert "return_1d" in derived.columns
    assert derived.loc[1, "return_1d"] == pytest.approx(0.02)


def test_stage_cross_asset_panel_writes_manifest_and_workspace_copy(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-16", "2026-06-17"]),
            "symbol": ["SPY", "SPY"],
            "open": [500.0, 501.0],
            "high": [502.0, 503.0],
            "low": [499.0, 500.0],
            "close": [501.0, 502.0],
            "volume": [1.0, 1.0],
            "return_1d": [0.0, 0.002],
            "return_5d": [0.0, 0.0],
            "return_20d": [0.0, 0.0],
            "return_60d": [0.0, 0.0],
            "volatility_20d": [0.0, 0.0],
            "drawdown_60d": [0.0, 0.0],
        }
    )
    seed.to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def fake_fetch(symbols, *, period="5d", strict=False):
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-18"]),
                "symbol": ["SPY"],
                "open": [503.0],
                "high": [504.0],
                "low": [502.0],
                "close": [503.5],
                "volume": [2.0],
            }
        )

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", fake_fetch)
    monkeypatch.setattr("harvester.cross_asset_panel.resolve_etf_universe", lambda workspace=None: ["SPY"])
    monkeypatch.chdir(workspace)

    release_dir = tmp_path / "release"
    info = stage_cross_asset_panel(
        release_dir,
        release_id="2026-06-18-r1",
        as_of_date="2026-06-18",
        vintage_date="2026-06-18",
        workspace=workspace,
    )

    assert info["row_count"] == 3
    assert (release_dir / "data" / "cross_asset_daily_panel.parquet").exists()
    assert (release_dir / "manifests" / "cross_asset_daily_panel.manifest.json").exists()
    assert (release_dir / "provenance" / "cross_asset_daily_panel.provenance.json").exists()
    assert (release_dir / "quality_reports" / "cross_asset_daily_panel.quality.json").exists()
    workspace_copy = workspace / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    assert workspace_copy.exists()
    copied = pd.read_parquet(workspace_copy)
    assert list(copied.columns) == PANEL_COLUMNS
    assert len(copied) == 3


def test_build_cross_asset_panel_returns_columns_when_seeded(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-17"]),
            "symbol": ["SPY"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
            "return_1d": [0.0],
            "return_5d": [0.0],
            "return_20d": [0.0],
            "return_60d": [0.0],
            "volatility_20d": [0.0],
            "drawdown_60d": [0.0],
        }
    ).to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", lambda symbols, period="5d": pd.DataFrame())
    monkeypatch.setattr("harvester.cross_asset_panel.resolve_etf_universe", lambda workspace=None: ["SPY"])

    panel = build_cross_asset_panel(workspace=workspace)
    assert not panel.empty
    assert set(PANEL_COLUMNS).issubset(panel.columns)


def test_fetch_recent_ohlcv_accepts_provider_value_column(monkeypatch) -> None:
    """EtfYfinanceProvider emits Close as 'value'; must not be dropped as close=0."""
    from harvester.cross_asset_panel import fetch_recent_ohlcv
    from harvester.providers.base import ProviderResult

    class FakeProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_series(self, series_ids):
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-07-10"]),
                    "value": [754.95],
                    "open": [752.0],
                    "high": [755.0],
                    "low": [751.0],
                    "volume": [1.0],
                }
            )
            return [
                ProviderResult(
                    provider="yfinance",
                    series_id="SPY",
                    frame=frame,
                )
            ]

    monkeypatch.setattr(
        "harvester.providers.etf_yfinance.EtfYfinanceProvider",
        FakeProvider,
    )
    fresh = fetch_recent_ohlcv(["SPY"], period="5d")
    assert len(fresh) == 1
    assert fresh.iloc[0]["close"] == pytest.approx(754.95)
    assert fresh.iloc[0]["symbol"] == "SPY"


def test_fetch_recent_ohlcv_strict_rejects_partial_provider_results(monkeypatch) -> None:
    from harvester.cross_asset_panel import fetch_recent_ohlcv
    from harvester.providers.base import ProviderResult

    class FakeProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_series(self, series_ids):
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-07-10"]),
                    "value": [754.95],
                    "open": [752.0],
                    "high": [755.0],
                    "low": [751.0],
                    "volume": [1.0],
                }
            )
            return [ProviderResult(provider="yfinance", series_id="SPY", frame=frame)]

    monkeypatch.setattr("harvester.providers.etf_yfinance.EtfYfinanceProvider", FakeProvider)
    with pytest.raises(RuntimeError, match=r"incomplete.*missing_symbols=QQQ"):
        fetch_recent_ohlcv(["SPY", "QQQ"], period="5d", strict=True)


def test_fetch_recent_ohlcv_raises_when_all_symbols_fail(monkeypatch) -> None:
    from harvester.cross_asset_panel import fetch_recent_ohlcv
    from harvester.providers.base import ProviderResult

    class FakeProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_series(self, series_ids):
            return [
                ProviderResult(
                    provider="yfinance",
                    series_id="SPY",
                    frame=pd.DataFrame(),
                    fetch_error="rate limited",
                    fetch_fallback_reason="rate_limited",
                )
            ]

    monkeypatch.setattr(
        "harvester.providers.etf_yfinance.EtfYfinanceProvider",
        FakeProvider,
    )
    with pytest.raises(RuntimeError, match=r"no usable rows.*provider_reasons=rate_limited"):
        fetch_recent_ohlcv(["SPY"], period="5d")


def test_build_retains_existing_when_fetch_raises(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-09", "2026-07-10"]),
            "symbol": ["SPY", "SPY"],
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [100.0, 101.0],
            "volume": [1.0, 1.0],
            "return_1d": [0.0, 0.01],
            "return_5d": [0.0, 0.0],
            "return_20d": [0.0, 0.0],
            "return_60d": [0.0, 0.0],
            "volatility_20d": [0.0, 0.0],
            "drawdown_60d": [0.0, 0.0],
        }
    )
    seed.to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def boom(symbols, *, period="5d"):
        raise RuntimeError("ETF fetch produced no usable rows for 1 symbols (1 failed/empty)")

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", boom)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY"],
    )

    panel = build_cross_asset_panel(workspace=workspace)
    assert len(panel) == 2
    assert panel["close"].iloc[-1] == pytest.approx(101.0)


def test_build_merges_by_symbol_date_not_date_only(tmp_path: Path, monkeypatch) -> None:
    """Partial fresh fetch must not delete other symbols on the same dates."""
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-09", "2026-07-09", "2026-07-10", "2026-07-10"]),
            "symbol": ["SPY", "QQQ", "SPY", "QQQ"],
            "open": [1.0, 1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0, 1.0],
            "close": [100.0, 200.0, 101.0, 201.0],
            "volume": [1.0, 1.0, 1.0, 1.0],
            "return_1d": [0.0, 0.0, 0.01, 0.005],
            "return_5d": [0.0, 0.0, 0.0, 0.0],
            "return_20d": [0.0, 0.0, 0.0, 0.0],
            "return_60d": [0.0, 0.0, 0.0, 0.0],
            "volatility_20d": [0.0, 0.0, 0.0, 0.0],
            "drawdown_60d": [0.0, 0.0, 0.0, 0.0],
        }
    )
    seed.to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def fake_fetch(symbols, *, period="5d"):
        # Only SPY refreshes for 2026-07-10; QQQ must be preserved.
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-07-10"]),
                "symbol": ["SPY"],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [102.0],
                "volume": [1.0],
            }
        )

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", fake_fetch)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY", "QQQ"],
    )

    panel = build_cross_asset_panel(workspace=workspace)
    qqq = panel[(panel["symbol"] == "QQQ") & (panel["date"] == pd.Timestamp("2026-07-10"))]
    spy = panel[(panel["symbol"] == "SPY") & (panel["date"] == pd.Timestamp("2026-07-10"))]
    assert len(qqq) == 1
    assert qqq.iloc[0]["close"] == pytest.approx(201.0)
    assert len(spy) == 1
    assert spy.iloc[0]["close"] == pytest.approx(102.0)


def test_sync_panel_writes_mirror_and_tolerates_readonly_canonical(tmp_path: Path) -> None:
    from harvester.cross_asset_panel import sync_panel_to_workspace

    workspace = tmp_path / "workspace"
    latest_data = workspace / "Data" / "harvester" / "exports" / "latest" / "data"
    latest_data.mkdir(parents=True)
    canonical = latest_data / "cross_asset_daily_panel.parquet"
    # Simulate finalized release: present but not writable.
    pd.DataFrame({"date": ["2026-06-04"], "close": [1.0]}).to_parquet(canonical, index=False)
    canonical.chmod(0o444)
    latest_data.chmod(0o555)

    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-10"]),
            "symbol": ["SPY"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [100.0],
            "volume": [1.0],
            "return_1d": [0.0],
            "return_5d": [0.0],
            "return_20d": [0.0],
            "return_60d": [0.0],
            "volatility_20d": [0.0],
            "drawdown_60d": [0.0],
        }
    )
    mirror = sync_panel_to_workspace(panel, workspace)
    assert mirror.exists()
    assert pd.read_parquet(mirror).iloc[0]["close"] == pytest.approx(100.0)
    # Canonical stays at prior content when read-only.
    assert pd.read_parquet(canonical).iloc[0]["close"] == pytest.approx(1.0)


def test_strict_build_does_not_reuse_stale_panel_after_fetch_failure(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-03"]),
            "symbol": ["SPY"],
            "close": [100.0],
        }
    )
    seed.to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def failed_fetch(symbols, *, period="5d", strict=False):
        raise RuntimeError("ETF fetch produced no usable rows")

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", failed_fetch)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY"],
    )

    with pytest.raises(RuntimeError, match="no usable rows"):
        build_cross_asset_panel(workspace=workspace, strict_fetch=True)


def test_strict_build_blocks_partial_symbol_coverage(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-06"]),
            "symbol": ["SPY"],
            "close": [100.0],
        }
    ).to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def partial_fetch(symbols, *, period="5d", strict=False):
        assert strict is True
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-08-07"]),
                "symbol": ["SPY"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1.0],
            }
        )

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", partial_fetch)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY", "QQQ"],
    )

    with pytest.raises(RuntimeError, match=r"incomplete.*QQQ"):
        build_cross_asset_panel(workspace=workspace, strict_fetch=True)


def test_empty_batch_uses_one_bounded_probe_instead_of_retrying_every_ticker(
    monkeypatch,
) -> None:
    from harvester.providers.base import ProviderResult
    from harvester.providers.etf_yfinance import EtfYfinanceProvider

    provider = EtfYfinanceProvider(tickers={"SPY": "SPY", "QQQ": "QQQ", "TLT": "TLT"})
    monkeypatch.setattr(provider, "_fetch_batch", lambda series_ids: {})
    calls: list[tuple[str, int]] = []

    def failed_probe(ticker: str, *, attempts: int = 2) -> ProviderResult:
        calls.append((ticker, attempts))
        return ProviderResult(
            provider="yfinance",
            series_id=ticker,
            frame=pd.DataFrame(),
            fetch_error="rate limited",
        )

    monkeypatch.setattr(provider, "_fetch_one", failed_probe)
    results = provider.fetch_series(["SPY", "QQQ", "TLT"])
    assert calls == [("SPY", 1)]
    assert [result.series_id for result in results] == ["SPY", "QQQ", "TLT"]
    assert all(result.frame.empty for result in results)


def test_yfinance_rate_limit_enters_cooldown_without_probe_or_fanout(
    tmp_path: Path, monkeypatch
) -> None:
    from harvester.providers.etf_yfinance import EtfYfinanceProvider

    calls: list[tuple[object, ...]] = []

    def rate_limited_download(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("YFRateLimitError: Too Many Requests")

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        types.SimpleNamespace(download=rate_limited_download),
    )
    provider = EtfYfinanceProvider(
        tickers={"SPY": "SPY", "QQQ": "QQQ"},
        data_root=str(tmp_path),
    )

    results = provider.fetch_series(["SPY", "QQQ"])

    assert len(calls) == 1  # one batch request; no probe and no serial fanout
    assert all(result.fetch_fallback_reason == "rate_limited" for result in results)
    state = tmp_path / "raw" / "yfinance" / "rate_limit_state.json"
    assert state.exists()

    def should_not_download(*args, **kwargs):
        raise AssertionError("cooldown must prevent a second network request")

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        types.SimpleNamespace(download=should_not_download),
    )
    cooled = EtfYfinanceProvider(
        tickers={"SPY": "SPY", "QQQ": "QQQ"},
        data_root=str(tmp_path),
    ).fetch_series(["SPY", "QQQ"])
    assert all(result.fetch_fallback_reason == "rate_limit_cooldown" for result in cooled)
