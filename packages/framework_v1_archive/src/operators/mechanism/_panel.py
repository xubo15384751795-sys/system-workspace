"""Helpers for reading harvester benchmark panels inside mechanism detectors."""

from __future__ import annotations

from typing import Iterable

import pandas as pd


def series_values(
    panel: pd.DataFrame,
    *candidates: str,
    as_of: pd.Timestamp | None = None,
) -> pd.Series:
    """Return a date-indexed value series for the first matching series_id."""
    if panel.empty or "series_id" not in panel.columns:
        return pd.Series(dtype=float)

    ids = set(panel["series_id"].astype(str))
    chosen = None
    for cand in candidates:
        if cand in ids:
            chosen = cand
            break
        # suffix match e.g. SOFR_IORB_SPREAD inside DERIVED:SOFR_IORB_SPREAD
        for sid in ids:
            if sid.endswith(cand) or cand in sid:
                chosen = sid
                break
        if chosen:
            break

    if not chosen:
        return pd.Series(dtype=float)

    frame = panel.loc[panel["series_id"] == chosen, ["date", "value"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    series = frame.set_index("date")["value"].astype(float)
    if as_of is not None:
        series = series.loc[:as_of]
    return series


def business_days(index: pd.DatetimeIndex, n: int) -> pd.DatetimeIndex:
    if len(index) < n:
        return index
    return index[-n:]


def held_daily(series: pd.Series, as_of: pd.Timestamp, lookback_days: int = 420) -> pd.Series:
    """Forward-fill sparse releases onto business days through *as_of*."""
    if series.empty:
        return series
    start = as_of - pd.Timedelta(days=lookback_days)
    sub = series.loc[series.index >= start]
    sub = sub.loc[:as_of].sort_index()
    if sub.empty:
        return sub
    idx = pd.bdate_range(sub.index.min(), as_of)
    return sub.reindex(idx).ffill()


def z_score(series: pd.Series, window: int) -> pd.Series:
    if series.empty:
        return series
    roll = series.rolling(window=window, min_periods=max(3, window // 2))
    mean = roll.mean()
    std = roll.std(ddof=0).replace(0, pd.NA)
    return (series - mean) / std


def pctile_rank(series: pd.Series, window: int) -> pd.Series:
    """Trailing percentile rank of the latest value within window (0–1)."""
    if series.empty:
        return series

    def _rank(vals: Iterable[float]) -> float:
        arr = pd.Series(list(vals)).dropna()
        if arr.empty:
            return float("nan")
        return float(arr.rank(pct=True).iloc[-1])

    return series.rolling(window=window, min_periods=max(5, window // 4)).apply(_rank, raw=False)


def delta_over_weeks(series: pd.Series, weeks: int = 4) -> pd.Series:
    """Approximate 4-week change for weekly series using ~20 business days."""
    if series.empty:
        return series
    step = 20 if weeks == 4 else weeks * 5
    return series - series.shift(step)
