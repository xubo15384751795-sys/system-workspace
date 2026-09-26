"""Canonical workspace data paths — prefer fresher Harvester evidence vs mirrors."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from verity.runtime.runtime_io import ROOT

HARVESTER_LATEST = ROOT / "Data" / "harvester" / "exports" / "latest"
HARVESTER_DATA = HARVESTER_LATEST / "data"


def _panel_max_date(path: Path) -> pd.Timestamp:
    frame = pd.read_parquet(path, columns=["date"])
    if frame.empty:
        return pd.Timestamp.min
    return pd.to_datetime(frame["date"]).max()


def _panel_row_count(path: Path) -> int:
    frame = pd.read_parquet(path, columns=["date"])
    return int(len(frame))


def resolve_cross_asset_panel_path() -> Path:
    """Return cross-asset panel path.

    Prefer the fresher of Harvester latest vs workspace mirror. Finalized
    Harvester releases are read-only, so weekly mirror refreshes can lead the
    immutable canonical copy until the next complete release.

    When max dates tie, prefer the panel with more rows so a truncated
    Harvester export cannot silently displace a complete mirror.
    """
    harvester = HARVESTER_DATA / "cross_asset_daily_panel.parquet"
    mirror = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    candidates = [path for path in (harvester, mirror) if path.exists()]
    if not candidates:
        return harvester
    if len(candidates) == 1:
        return candidates[0]
    return max(candidates, key=lambda path: (_panel_max_date(path), _panel_row_count(path)))


def resolve_benchmark_panel_path() -> Path:
    """Return benchmark panel path from Harvester latest release."""
    return HARVESTER_DATA / "benchmark_panel.parquet"
