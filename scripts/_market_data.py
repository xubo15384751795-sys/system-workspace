"""Shared market data loading utilities.

Consolidates panel loading, close-matrix construction, and FRED CSV
parsing used by feedback replay and evaluation scripts.

Public API:
    load_panel, build_close_matrix, load_fred_csv
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def load_panel(path: Path) -> pd.DataFrame:
    """Load cross-asset panel parquet, indexed by date with symbol columns."""
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    return df


def build_close_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    """Build date x symbol close price matrix from a panel DataFrame.

    Uses per-symbol Series construction to avoid pandas groupby/unstack
    index corruption on large panels.
    """
    symbols = sorted(panel["symbol"].unique())
    series_map = {}
    for sym in symbols:
        sub = panel[panel["symbol"] == sym][["date", "close"]].set_index("date")["close"]
        series_map[sym] = sub
    return pd.DataFrame(series_map).sort_index()


def load_fred_csv(path: Path) -> pd.Series | None:
    """Load a FRED CSV as a date-indexed Series of float values.

    Returns None if the file is missing or cannot be parsed.
    """
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["DATE"], index_col="DATE")
        col = df.columns[0]
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        s.index = pd.to_datetime(s.index)
        return s
    except Exception:
        logger.debug("Failed to load FRED CSV from %s", path, exc_info=True)
        return None
