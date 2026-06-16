#!/usr/bin/env python3
"""Refresh ETF panel from OpenBB and update K features.

Fetches latest daily prices for all 33 ETFs in the cross-asset panel,
appends new data, and re-runs K feature computation.

Usage:
    python3 scripts/refresh_etf_panel.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
K_FEATURES_PATH = ROOT / "Data" / "features" / "k_features_daily.csv"


def fetch_etf_data(symbols: list[str], start_date: str) -> pd.DataFrame:
    """Fetch ETF data from OpenBB."""
    from openbb import obb

    all_rows = []
    for symbol in symbols:
        try:
            df = obb.equity.price.historical(
                symbol, start_date=start_date, provider="yfinance"
            ).to_df()
            if df.empty:
                continue
            df = df.reset_index()
            df["symbol"] = symbol
            df = df.rename(columns={"date": "date", "close": "close"})
            all_rows.append(df[["date", "symbol", "open", "high", "low", "close", "volume"]])
        except Exception as e:
            print(f"  {symbol}: failed ({e})")

    if not all_rows:
        return pd.DataFrame()

    combined = pd.concat(all_rows, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"]).dt.normalize()
    return combined


def refresh_panel():
    """Refresh the ETF panel with latest data."""
    if not PANEL_PATH.exists():
        print(f"Panel not found: {PANEL_PATH}")
        return

    existing = pd.read_parquet(PANEL_PATH)
    existing["date"] = pd.to_datetime(existing["date"]).dt.normalize()
    symbols = sorted(existing["symbol"].unique())
    last_date = existing["date"].max()
    start_date = (last_date - pd.Timedelta(days=5)).strftime("%Y-%m-%d")

    print(f"Existing panel: {len(existing)} rows, {len(symbols)} symbols, last={last_date.date()}")
    print(f"Fetching from {start_date}...")

    new_data = fetch_etf_data(symbols, start_date)
    if new_data.empty:
        print("No new data fetched.")
        return

    new_data = new_data[new_data["date"] > last_date]
    if new_data.empty:
        print("No new dates beyond existing panel.")
        return

    print(f"New data: {len(new_data)} rows, {new_data['date'].min().date()} to {new_data['date'].max().date()}")

    # Append and save
    combined = pd.concat([existing, new_data], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "symbol"], keep="last")
    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)
    combined.to_parquet(PANEL_PATH, index=False)
    print(f"Updated panel: {len(combined)} rows, last={combined['date'].max().date()}")


def update_k_features():
    """Re-run K feature computation."""
    sys.path.insert(0, str(ROOT / "scripts"))
    # Import and run
    import importlib.util
    spec = importlib.util.spec_from_file_location("k_features", str(ROOT / "scripts" / "k_features_from_etf.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # The script runs on import if __name__ == "__main__"
    # Call the main function directly
    if hasattr(mod, "main"):
        mod.main()
    else:
        # Re-run the script
        exec(open(ROOT / "scripts" / "k_features_from_etf.py").read())


if __name__ == "__main__":
    print("=== Refresh ETF Panel ===")
    refresh_panel()
    print()
    print("=== Update K Features ===")
    update_k_features()
    print()
    # Verify
    if K_FEATURES_PATH.exists():
        df = pd.read_csv(K_FEATURES_PATH)
        filled = df[df["rv_SPY_20d"].notna()]
        print(f"K features: {len(df)} rows, last filled={filled['date'].iloc[-1]}")
