"""Data loader — align SPY prices with neutral macro-pressure history.

Reads from:
  - Data/panels/cross_asset_daily_panel.parquet  (SPY OHLCV)
  - Run-local neutral pressure history named by the current snapshot

Returns a single aligned DataFrame with one row per trading day.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import _runtime_io as rio


# ── Paths ────────────────────────────────────────────────────────────
def _cross_asset_panel_path() -> Path:
    from scripts._data_paths import resolve_cross_asset_panel_path

    return resolve_cross_asset_panel_path()


PANEL_PATH = _cross_asset_panel_path()
LEGACY_SIGNAL_PATH = rio.ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"

# ── Column mapping from all_signals.parquet ──────────────────────────
SIGNAL_COLS = {
    "channel_M": "M",
    "channel_D_contraction": "D",
    "channel_K": "K",
    "channel_X_agg": "X",
}


def load_spy(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Load SPY daily close + returns from the cross-asset panel.

    Returns DataFrame indexed by date with columns:
        close, return_1d, return_5d, return_20d, return_60d, volatility_20d
    """
    panel = pd.read_parquet(PANEL_PATH)
    spy = panel[panel["symbol"] == "SPY"].copy()
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.set_index("date").sort_index()
    spy = spy[["close", "return_1d", "return_5d", "return_20d", "return_60d", "volatility_20d"]]
    if start:
        spy = spy.loc[start:]
    if end:
        spy = spy.loc[:end]
    return spy


def load_symbol(symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Load daily close for any symbol from the cross-asset panel.

    Returns DataFrame indexed by date with columns: close, return_1d.
    """
    panel = pd.read_parquet(PANEL_PATH)
    sym = panel[panel["symbol"] == symbol].copy()
    sym["date"] = pd.to_datetime(sym["date"])
    sym = sym.set_index("date").sort_index()
    sym = sym[["close", "return_1d"]]
    if start:
        sym = sym.loc[start:]
    if end:
        sym = sym.loc[:end]
    return sym


def load_signals(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Load neutral funding-mismatch and market-constraint gauges.

    The M/D column names are compatibility keys only. K/X are deliberately
    absent because they are unresolved research candidates.
    """
    snapshot_path = rio.current_dir() / "neutral_pressure_snapshot.json"
    snapshot = rio.load_json(snapshot_path)
    history_raw = ((snapshot or {}).get("artifacts") or {}).get("pressure_history")
    if not history_raw:
        raise FileNotFoundError(f"neutral pressure history not declared by {snapshot_path}")
    history_path = Path(str(history_raw))
    sig = pd.read_parquet(history_path)[["M", "D"]]
    sig.index = pd.to_datetime(sig.index)
    sig = sig.sort_index()
    if start:
        sig = sig.loc[start:]
    if end:
        sig = sig.loc[:end]
    return sig


def load_aligned(
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load SPY + neutral pressure gauges aligned on date.

    Returns DataFrame indexed by date with columns:
        close, return_1d, M, D
    Only rows where both gauges are non-null are kept.
    """
    spy = load_spy(start, end)
    sig = load_signals(start, end)

    # Inner join on date — only days with both price and signal data
    merged = spy.join(sig, how="inner")

    # Drop rows where any signal is NaN
    merged = merged.dropna(subset=["M", "D"])

    return merged
