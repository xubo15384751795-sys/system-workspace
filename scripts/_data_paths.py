"""Canonical workspace data paths — prefer Harvester evidence over mirrors."""
from __future__ import annotations

from pathlib import Path

from _runtime_io import ROOT

HARVESTER_LATEST = ROOT / "Data" / "harvester" / "exports" / "latest"
HARVESTER_DATA = HARVESTER_LATEST / "data"


def resolve_cross_asset_panel_path() -> Path:
    """Return cross-asset panel path; Harvester release preferred over workspace mirror."""
    harvester = HARVESTER_DATA / "cross_asset_daily_panel.parquet"
    mirror = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    if harvester.exists():
        return harvester
    return mirror


def resolve_benchmark_panel_path() -> Path:
    """Return benchmark panel path from Harvester latest release."""
    return HARVESTER_DATA / "benchmark_panel.parquet"
