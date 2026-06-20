#!/usr/bin/env python3
"""Refresh cross-asset daily panel with latest market data.

Fetches latest OHLCV from yfinance for all symbols in the panel,
merges with existing data, recomputes derived columns (returns, volatility,
drawdown), and writes back.

Usage:
    python3 scripts/refresh_cross_asset_panel.py
    python3 scripts/refresh_cross_asset_panel.py --days 30  # only fetch last 30 days

Output:
    Data/panels/cross_asset_daily_panel.parquet  (updated in place)
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from _runtime_io import ROOT

PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"


def _fetch_yfinance(symbols: list[str], period: str = "5d") -> pd.DataFrame:
    """Fetch latest OHLCV via Harvester's yfinance provider."""
    import sys
    sys.path.insert(0, str(ROOT / "structural-risk-harvester" / "src"))
    from harvester.providers.etf_yfinance import EtfYfinanceProvider

    # Map symbols to tickers dict expected by provider
    tickers = {s: s for s in symbols}
    provider = EtfYfinanceProvider(tickers=tickers, period=period)
    results = provider.fetch_series(symbols)

    rows = []
    for r in results:
        if r.frame is not None and not r.frame.empty:
            for _, row in r.frame.iterrows():
                rows.append({
                    "date": str(row.get("date", ""))[:10],
                    "symbol": r.series_id,
                    "close": float(row.get("close", 0)),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "volume": float(row.get("volume", 0)),
                })
    return pd.DataFrame(rows)


def _compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Compute return_1d/5d/20d/60d, volatility_20d, drawdown_60d per symbol."""
    result_parts = []
    for symbol, group in df.groupby("symbol"):
        g = group.sort_values("date").copy()
        close = g["close"].astype(float)

        g["return_1d"] = close.pct_change(1)
        g["return_5d"] = close.pct_change(5)
        g["return_20d"] = close.pct_change(20)
        g["return_60d"] = close.pct_change(60)
        g["volatility_20d"] = close.pct_change(1).rolling(20, min_periods=10).std() * np.sqrt(252)
        rolling_max = close.rolling(60, min_periods=20).max()
        g["drawdown_60d"] = (close - rolling_max) / rolling_max

        result_parts.append(g)

    return pd.concat(result_parts, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=5, help="Days to fetch from yfinance")
    args = parser.parse_args()

    if not PANEL_PATH.exists():
        print(f"Panel not found: {PANEL_PATH}")
        return

    # Load existing panel
    existing = pd.read_parquet(PANEL_PATH)
    existing["date"] = pd.to_datetime(existing["date"])
    symbols = sorted(existing["symbol"].unique())
    last_date = existing["date"].max()
    print(f"Existing panel: {len(existing)} rows, {len(symbols)} symbols, through {last_date.date()}")

    # Fetch latest data
    period = f"{args.days}d"
    print(f"Fetching {period} of data for {len(symbols)} symbols...")
    new_data = _fetch_yfinance(symbols, period=period)

    if new_data.empty:
        print("  No new data fetched")
        return

    new_data["date"] = pd.to_datetime(new_data["date"])
    print(f"  Fetched {len(new_data)} rows, {new_data['date'].min().date()} to {new_data['date'].max().date()}")

    # Merge: remove existing rows for dates we're updating, then append
    new_dates = new_data["date"].unique()
    merged = existing[~existing["date"].isin(new_dates)]
    merged = pd.concat([merged, new_data], ignore_index=True)

    # Fill missing columns
    for col in existing.columns:
        if col not in merged.columns:
            merged[col] = np.nan
    merged = merged[existing.columns]

    # Recompute derived columns
    merged = _compute_derived(merged)
    merged = merged.sort_values(["symbol", "date"]).reset_index(drop=True)

    # Write back
    merged.to_parquet(PANEL_PATH, index=False)
    spy = merged[merged["symbol"] == "SPY"]
    print(f"Updated panel: {len(merged)} rows, through {merged['date'].max().date()}")
    print(f"SPY: through {spy['date'].max().date()}, latest return_1d={spy['return_1d'].iloc[-1]:.4f}")


if __name__ == "__main__":
    main()
