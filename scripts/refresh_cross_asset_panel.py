#!/usr/bin/env python3
"""Refresh cross-asset daily panel with latest market data.

Updates the writable workspace mirror at
`Data/panels/cross_asset_daily_panel.parquet`. Finalized Harvester releases
under `Data/harvester/exports/latest/` are read-only; consumers resolve the
fresher of mirror vs canonical via `_data_paths.resolve_cross_asset_panel_path`
(and k_gate's matching helper). A complete Harvester
`stage_complete_release` refreshes the immutable canonical copy.

Usage:
    python3 scripts/refresh_cross_asset_panel.py
    python3 scripts/refresh_cross_asset_panel.py --days 30

Output:
    Data/panels/cross_asset_daily_panel.parquet
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from scripts._runtime_io import ROOT

PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
HARVESTER_PANEL_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "cross_asset_daily_panel.parquet"


def _panel_max_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=["date"])
    if frame.empty:
        return None
    return pd.to_datetime(frame["date"]).max()


def _harvester_build(*, fetch_period: str) -> pd.DataFrame:
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

    prior_max = _panel_max_date(PANEL_PATH) or _panel_max_date(HARVESTER_PANEL_PATH)
    period = f"{args.days}d"
    print(f"Refreshing cross-asset panel via Harvester builder ({period})...")
    merged = _harvester_build(fetch_period=period)

    if merged.empty:
        raise SystemExit("No panel data produced")

    new_max = pd.to_datetime(merged["date"]).max()
    spy = merged[merged["symbol"] == "SPY"]
    print(f"Updated mirror: {len(merged)} rows, through {new_max.date()} -> {PANEL_PATH}")
    if HARVESTER_PANEL_PATH.exists():
        canon_max = _panel_max_date(HARVESTER_PANEL_PATH)
        print(
            f"Harvester canonical (read-only): through "
            f"{canon_max.date() if canon_max is not None else 'n/a'}"
        )
    if not spy.empty:
        print(f"SPY: through {spy['date'].max().date()}, latest return_1d={spy['return_1d'].iloc[-1]:.4f}")

    if prior_max is not None and new_max <= prior_max:
        print(
            f"WARNING: panel did not advance (still through {new_max.date()}); "
            "check yfinance rate limits / fetch errors"
        )


if __name__ == "__main__":
    main()
