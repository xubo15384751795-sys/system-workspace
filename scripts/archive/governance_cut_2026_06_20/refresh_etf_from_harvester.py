#!/usr/bin/env python3
"""Refresh ETF panel via Harvester provider.

This script uses the Harvester's EtfYfinanceProvider to acquire ETF data,
then merges it into the local cross_asset_daily_panel.parquet and recomputes
K features.  This is the sanctioned Harvester path — root scripts must not
call yfinance directly.

Usage:
    python3 scripts/refresh_etf_from_harvester.py
    python3 scripts/refresh_etf_from_harvester.py --days 5
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
K_FEATURES_PATH = ROOT / "Data" / "features" / "k_features_daily.csv"

from _workspace_imports import add_harvester_src
add_harvester_src()


def _compute_k_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute K features from ETF panel (close prices and returns)."""
    if panel.empty:
        return pd.DataFrame()

    # Build pivot manually to avoid pandas pivot_table index corruption
    symbols = sorted(panel["symbol"].unique())
    dates = sorted(panel["date"].unique())
    data = {}
    for sym in symbols:
        sym_data = panel[panel["symbol"] == sym].set_index("date")["close"]
        data[sym] = sym_data
    pivot = pd.DataFrame(data, index=dates)
    pivot.index.name = "date"

    features = pd.DataFrame(index=pivot.index)
    features.index.name = "date"

    # Realized volatility (20-day rolling)
    returns = pivot.pct_change()
    for col in pivot.columns:
        features[f"rv_{col}_20d"] = returns[col].rolling(20).std() * (252 ** 0.5)
        features[f"ret_5d_{col}"] = pivot[col].pct_change(5)
        features[f"drawdown_60d_{col}"] = pivot[col] / pivot[col].rolling(60).max() - 1

    # Cross-asset ratios
    if "SPY" in pivot.columns and "TLT" in pivot.columns:
        features["ratio_SPY_TLT"] = pivot["SPY"] / pivot["TLT"]
    if "HYG" in pivot.columns and "LQD" in pivot.columns:
        features["ratio_HYG_LQD"] = pivot["HYG"] / pivot["LQD"]
    if "XLF" in pivot.columns and "SPY" in pivot.columns:
        features["ratio_XLF_SPY"] = pivot["XLF"] / pivot["SPY"]

    # Level columns for key tickers
    for col in ("SPY", "HYG", "TLT", "UUP", "GLD"):
        if col in pivot.columns:
            features[f"{col}_level"] = pivot[col]

    return features.reset_index()


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh ETF panel via Harvester")
    parser.add_argument("--days", type=int, default=60, help="Lookback period for yfinance")
    args = parser.parse_args()

    if not PANEL_PATH.exists():
        print(f"ERROR: ETF panel not found: {PANEL_PATH}")
        sys.exit(1)

    # Load existing panel
    existing = pd.read_parquet(PANEL_PATH)
    existing["date"] = pd.to_datetime(existing["date"])
    existing_max = existing["date"].max()
    print(f"Existing panel: {len(existing)} rows, last date: {existing_max.date()}")

    # Fetch via Harvester provider
    try:
        from harvester.providers.etf_yfinance import EtfYfinanceProvider
    except ImportError:
        print("ERROR: Harvester ETF provider not found. Install structural-risk-harvester.")
        sys.exit(1)

    provider = EtfYfinanceProvider(period=f"{args.days}d")
    tickers = list(set(existing["symbol"].unique()))
    print(f"Fetching {len(tickers)} tickers via Harvester (period={args.days}d)...")
    results = provider.fetch_series(tickers)

    # Merge new data
    new_rows = []
    for result in results:
        if result.empty():
            print(f"  WARN: {result.series_id} returned no data")
            continue
        df = result.frame.copy()
        df["date"] = pd.to_datetime(df["date"])
        # Only keep rows newer than existing data
        df = df[df["date"] > existing_max]
        if df.empty:
            continue
        symbol = result.series_id
        # Build rows matching existing panel schema
        for _, row in df.iterrows():
            new_rows.append({
                "date": row["date"],
                "symbol": symbol,
                "group": None,
                "close": row["value"],
                "return_1d": None,  # will be computed after merge
                "high": row.get("high"),
                "low": row.get("low"),
                "volume": row.get("volume"),
            })

    if not new_rows:
        print("No new data to merge.")
        return

    new_df = pd.DataFrame(new_rows)
    print(f"New data: {len(new_df)} rows for {new_df['symbol'].nunique()} symbols")

    # Merge
    merged = pd.concat([existing, new_df], ignore_index=True)
    merged = merged.sort_values(["date", "symbol"]).drop_duplicates(
        subset=["date", "symbol"], keep="last"
    ).reset_index(drop=True)

    # Recompute returns
    for symbol in merged["symbol"].unique():
        mask = merged["symbol"] == symbol
        sym_data = merged.loc[mask].sort_values("date")
        merged.loc[mask, "return_1d"] = sym_data["close"].pct_change()
        merged.loc[mask, "return_5d"] = sym_data["close"].pct_change(5)
        merged.loc[mask, "return_20d"] = sym_data["close"].pct_change(20)
        merged.loc[mask, "return_60d"] = sym_data["close"].pct_change(60)
        merged.loc[mask, "volatility_20d"] = sym_data["close"].pct_change().rolling(20).std() * (252 ** 0.5)
        merged.loc[mask, "drawdown_60d"] = sym_data["close"] / sym_data["close"].rolling(60).max() - 1

    # Save
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(PANEL_PATH, index=False)
    print(f"Saved: {PANEL_PATH} ({len(merged)} rows, last date: {merged['date'].max().date()})")

    # Recompute K features
    print("Recomputing K features...")
    k_features = _compute_k_features(merged)
    K_FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    k_features.to_csv(K_FEATURES_PATH, index=False)
    print(f"Saved: {K_FEATURES_PATH} ({len(k_features)} rows)")

    # Summary
    new_max = merged["date"].max()
    print(f"\nPanel updated: {existing_max.date()} → {new_max.date()}")
    print(f"New trading days: {(new_max - existing_max).days}")


if __name__ == "__main__":
    main()
