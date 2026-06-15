#!/usr/bin/env python3
"""Compute K features from existing ETF panel.

No new data needed — uses the 33-ETF cross-asset panel.

Features:
  - Realized vol (20d, 60d) for SPY, QQQ, XLF, HYG, TLT
  - Rolling correlation (60d) for SPY/TLT, SPY/HYG, SPY/GLD, HYG/TLT
  - Cross-asset dispersion (sector return std dev)
  - Drawdown velocity (max drawdown speed)
  - ETF ratios: QQQ/SPY, IWM/SPY, SMH/SPY, KRE/XLF, HYG/TLT, SLV/GLD

Output: Data/features/k_features_daily.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Data" / "features"
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"


def load_etf() -> pd.DataFrame:
    etf = pd.read_parquet(ETF_PANEL)
    etf["date"] = pd.to_datetime(etf["date"])
    return etf


def pivot_close(etf: pd.DataFrame) -> pd.DataFrame:
    """Pivot ETF panel to wide format (date x symbol)."""
    wide = etf.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    return wide.sort_index()


def compute_returns(close: pd.DataFrame, periods: list[int] = [1, 5, 20, 60]) -> dict[str, pd.DataFrame]:
    """Compute log returns for various periods."""
    rets = {}
    for p in periods:
        rets[f"ret_{p}d"] = np.log(close / close.shift(p))
    return rets


def compute_realized_vol(rets: pd.DataFrame, windows: list[int] = [20, 60]) -> pd.DataFrame:
    """Compute rolling realized volatility."""
    vol = pd.DataFrame(index=rets.index)
    targets = ["SPY", "QQQ", "IWM", "XLF", "HYG", "TLT"]
    for sym in targets:
        if sym in rets.columns:
            for w in windows:
                vol[f"rv_{sym}_{w}d"] = rets[sym].rolling(w, min_periods=w // 2).std() * np.sqrt(252)
    return vol


def compute_rolling_corr(close: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Compute rolling correlations between asset pairs."""
    pairs = [
        ("SPY", "TLT"), ("SPY", "HYG"), ("SPY", "GLD"),
        ("HYG", "TLT"), ("QQQ", "TLT"), ("SPY", "UUP"),
    ]
    corr = pd.DataFrame(index=close.index)
    for a, b in pairs:
        if a in close.columns and b in close.columns:
            corr[f"corr_{a}_{b}_{window}d"] = close[a].pct_change().rolling(window, min_periods=window // 2).corr(
                close[b].pct_change()
            )
    return corr


def compute_dispersion(close: pd.DataFrame, window: int = 20) -> pd.Series:
    """Compute cross-asset dispersion (sector return std dev)."""
    sectors = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
    available = [s for s in sectors if s in close.columns]
    if len(available) < 3:
        return pd.Series(dtype=float, index=close.index)
    rets = close[available].pct_change()
    rolling_std = rets.rolling(window, min_periods=window // 2).std()
    dispersion = rolling_std.mean(axis=1) * np.sqrt(252)
    dispersion.name = f"sector_dispersion_{window}d"
    return dispersion


def compute_drawdown_velocity(close: pd.DataFrame, windows: list[int] = [5, 10, 20]) -> pd.DataFrame:
    """Compute drawdown velocity (speed of decline)."""
    dd = pd.DataFrame(index=close.index)
    targets = ["SPY", "QQQ", "XLF"]
    for sym in targets:
        if sym not in close.columns:
            continue
        cummax = close[sym].cummax()
        drawdown = (close[sym] - cummax) / cummax
        for w in windows:
            # Min drawdown over rolling window (most negative = worst)
            dd[f"dd_vel_{sym}_{w}d"] = drawdown.rolling(w, min_periods=w // 2).min()
    return dd


def compute_etf_ratios(close: pd.DataFrame) -> pd.DataFrame:
    """Compute cross-asset ratios."""
    ratios = pd.DataFrame(index=close.index)
    pairs = {
        "QQQ_SPY": ("QQQ", "SPY"),
        "IWM_SPY": ("IWM", "SPY"),
        "SMH_SPY": ("SMH", "SPY"),
        "KRE_XLF": ("KRE", "XLF"),
        "HYG_TLT": ("HYG", "TLT"),
        "SLV_GLD": ("SLV", "GLD"),
        "XLF_SPY": ("XLF", "SPY"),
    }
    for name, (num, den) in pairs.items():
        if num in close.columns and den in close.columns:
            ratios[f"ratio_{name}"] = close[num] / close[den]
    if "UUP" in close.columns:
        ratios["UUP_level"] = close["UUP"]
    return ratios


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("Loading ETF panel...")
    etf = load_etf()
    close = pivot_close(etf)
    print(f"  {len(close)} dates, {len(close.columns)} symbols")

    print("Computing returns...")
    rets = compute_returns(close)

    print("Computing realized vol...")
    rv = compute_realized_vol(rets["ret_1d"])

    print("Computing rolling correlations...")
    corr = compute_rolling_corr(close)

    print("Computing sector dispersion...")
    disp20 = compute_dispersion(close, 20)
    disp60 = compute_dispersion(close, 60)

    print("Computing drawdown velocity...")
    dd = compute_drawdown_velocity(close)

    print("Computing ETF ratios...")
    ratios = compute_etf_ratios(close)

    # Combine all features
    features = pd.concat([
        rv, corr,
        disp20.to_frame(), disp60.to_frame(),
        dd, ratios,
    ], axis=1)

    # Write
    out_path = OUTPUT / "k_features_daily.csv"
    features.to_csv(out_path)
    print(f"\nWrote: {out_path}")
    print(f"  {len(features)} rows, {len(features.columns)} features")
    print(f"  Date range: {features.index.min()} to {features.index.max()}")
    print(f"  Features: {list(features.columns)}")

    # Summary stats
    print("\n=== Feature Summary ===")
    for col in features.columns:
        nn = features[col].notna().sum()
        last = features[col].dropna().iloc[-1] if nn > 0 else None
        print(f"  {col}: {nn:,} obs, last={last:.4f}" if last is not None else f"  {col}: {nn:,} obs")

    print("\nDone.")


if __name__ == "__main__":
    main()
