"""Tests for cross-asset panel Harvester dataset staging."""
from __future__ import annotations

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

    def fake_fetch(symbols, *, period="5d"):
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
