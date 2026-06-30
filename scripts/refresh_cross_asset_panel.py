#!/usr/bin/env python3
"""Refresh cross-asset daily panel with latest market data.

Canonical source: Harvester evidence release
`Data/harvester/exports/latest/data/cross_asset_daily_panel.parquet`.
This script refreshes the workspace mirror at Data/panels/ using the same
Harvester builder (`harvester.cross_asset_panel`).

Usage:
    python3 scripts/refresh_cross_asset_panel.py
    python3 scripts/refresh_cross_asset_panel.py --days 30

Output:
    Data/panels/cross_asset_daily_panel.parquet  (updated in place)
"""
from __future__ import annotations

import argparse

import pandas as pd
from _runtime_io import ROOT
from _workspace_imports import add_harvester_src

PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
HARVESTER_PANEL_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "cross_asset_daily_panel.parquet"


def _harvester_build(*, fetch_period: str) -> pd.DataFrame:
    add_harvester_src()
    from harvester.cross_asset_panel import (  # noqa: I001
        build_cross_asset_panel,
        sync_panel_to_workspace,
    )

    panel = build_cross_asset_panel(workspace=ROOT, fetch_period=fetch_period)
    sync_panel_to_workspace(panel, ROOT)
    return panel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=5, help="Days to fetch from yfinance")
    args = parser.parse_args()

    period = f"{args.days}d"
    print(f"Refreshing cross-asset panel via Harvester builder ({period})...")
    merged = _harvester_build(fetch_period=period)

    if merged.empty:
        print("  No panel data produced")
        return

    spy = merged[merged["symbol"] == "SPY"]
    print(f"Updated panel: {len(merged)} rows, through {merged['date'].max().date()}")
    if HARVESTER_PANEL_PATH.exists():
        print(f"Harvester canonical: {HARVESTER_PANEL_PATH}")
    if not spy.empty:
        print(f"SPY: through {spy['date'].max().date()}, latest return_1d={spy['return_1d'].iloc[-1]:.4f}")


if __name__ == "__main__":
    main()
