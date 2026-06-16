#!/usr/bin/env python3
"""Update K features from the admitted ETF panel.

This script no longer acquires ETF prices. Root scripts are not allowed to call
OpenBB or any external provider directly; ETF acquisition must be implemented in
Harvester and published as an evidence bundle. Until that Harvester path exists,
this step only recomputes K features from the already-admitted local panel.

Usage:
    python3 scripts/refresh_etf_panel.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
K_FEATURES_PATH = ROOT / "Data" / "features" / "k_features_daily.csv"


def check_panel() -> None:
    """Report current ETF panel coverage without acquiring data."""
    if not PANEL_PATH.exists():
        raise SystemExit(
            f"ETF panel not found: {PANEL_PATH}\n"
            "ETF acquisition must run through Harvester before this step can compute features."
        )

    existing = pd.read_parquet(PANEL_PATH)
    existing["date"] = pd.to_datetime(existing["date"]).dt.normalize()
    symbols = sorted(existing["symbol"].unique())
    last_date = existing["date"].max()
    print(f"ETF panel: {len(existing)} rows, {len(symbols)} symbols, last={last_date.date()}")
    print("Acquisition skipped: ETF refresh must be implemented as a Harvester evidence release.")


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
    print("=== ETF Panel Boundary Check ===")
    check_panel()
    print()
    print("=== Update K Features ===")
    update_k_features()
    print()
    # Verify
    if K_FEATURES_PATH.exists():
        df = pd.read_csv(K_FEATURES_PATH)
        filled = df[df["rv_SPY_20d"].notna()]
        print(f"K features: {len(df)} rows, last filled={filled['date'].iloc[-1]}")
