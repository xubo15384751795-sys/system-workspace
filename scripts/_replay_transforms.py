"""Replay transforms — pure helper functions for proxy computation.

Stateless transform functions: z-score, spread, butterfly, activation scores.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from _constants import HALF_YEAR_TRADING_DAYS, TRADING_DAYS_PER_YEAR

Freq = Literal["daily", "weekly", "monthly", "quarterly", "sparse", "mixed"]

def _series(panel: pd.DataFrame, col: str, limit: int = 5) -> pd.Series | None:
    if col not in panel.columns:
        return None
    return panel[col].astype(float).interpolate(limit=limit)


def _spread(panel: pd.DataFrame, left: str, right: str, limit: int = 5) -> pd.Series | None:
    lhs = _series(panel, left, limit)
    rhs = _series(panel, right, limit)
    if lhs is None or rhs is None:
        return None
    return lhs - rhs


def _butterfly(panel: pd.DataFrame, short: str, mid: str, long: str, limit: int = 5) -> pd.Series | None:
    """Curvature (butterfly) of a three-tenor term structure: short - 2*mid + long.

    Level-independent measure of term-structure twist/distortion: ~0 for a
    smooth monotone curve, nonzero when the curve kinks (e.g. front-end vol
    inversion under stress). Used for canonical K u1 (IV term-structure twist).
    """
    s = _series(panel, short, limit)
    m = _series(panel, mid, limit)
    lng = _series(panel, long, limit)
    if s is None or m is None or lng is None:
        return None
    return s - 2.0 * m + lng


FREQ_WINDOWS: dict[Freq, tuple[int, int]] = {
    "daily":   (TRADING_DAYS_PER_YEAR, HALF_YEAR_TRADING_DAYS),  # 1y rolling, 6m warmup
    "weekly":  (52, 26),    # 1y rolling in weekly observations
    "monthly": (12, 6),     # 1y rolling in monthly observations
    "quarterly": (20, 8),   # 5y rolling in quarterly observations (1y is too few obs)
}

FREQ_SMOOTH_DEFAULT: dict[Freq, int] = {
    "daily":   21,
    "weekly":  3,
    "monthly": 1,
    "quarterly": 1,
    "sparse":  5,
}

PANDAS_RESAMPLE_RULE: dict[Freq, str] = {
    "weekly":  "W-FRI",
    "monthly": "ME",
    "quarterly": "QE",
}


def _rolling_zscore(series: pd.Series, window: int = TRADING_DAYS_PER_YEAR, min_periods: int = HALF_YEAR_TRADING_DAYS) -> pd.Series:
    """Causal rolling z-score with no look-ahead and explicit missing values."""
    mu = series.rolling(window=window, min_periods=min_periods).mean()
    sigma = series.rolling(window=window, min_periods=min_periods).std().replace(0, np.nan)
    return ((series - mu) / sigma).clip(-4, 4)


def _freq_aware_zscore(series: pd.Series, freq: Freq) -> pd.Series:
    """Rolling z-score with the window scaled to the data's natural frequency.

    For weekly / monthly series the input is daily-aligned but the underlying
    cadence is sparser, so we resample to native frequency, run a same-horizon
    z-score there, and forward-fill back to daily so it can join the unified
    daily channel index.
    """
    if freq == "daily":
        w, mp = FREQ_WINDOWS["daily"]
        return _rolling_zscore(series, w, mp)

    if freq in ("weekly", "monthly", "quarterly"):
        rule = PANDAS_RESAMPLE_RULE[freq]
        native = series.dropna().resample(rule).last()
        if native.empty:
            return pd.Series(np.nan, index=series.index)
        w, mp = FREQ_WINDOWS[freq]
        z_native = _rolling_zscore(native, w, mp)
        # Forward-fill to daily index, but limit fill so old observations
        # don't creep into long gaps.
        max_fill = {"weekly": 7, "monthly": 35, "quarterly": 100}[freq]
        return z_native.reindex(series.index, method="ffill", limit=max_fill)

    raise ValueError(f"_freq_aware_zscore: unsupported freq {freq!r}")


def _jump_activation_score(
    series: pd.Series | None,
    smooth: int = 5,
) -> pd.Series | None:
    """Daily jump-driven activation score for continuous market-side series.

    Used for VIX / HY OAS where forced realization shows up as discrete shock
    days rather than facility usage. Pipeline:
        |Δ series(1d)| → rolling `smooth`-day mean
                       → daily 252d rolling z-score
                       → take positive part (clip to [0, 4])
    Output mirrors the shape of `_sparse_activation_score`: ≈ 0 in calm
    regimes, ≥1 during shock days.

    Phase 5: smooth shortened from 21d to 5d. The longer 21-day decay let a
    single VIX shock keep the score elevated for ~3 weeks even when markets
    had already calmed, inflating false_activation_rate. 5d means a shock
    decays back to baseline within a week, matching the physical "forced
    realization" half-life.

    The "positive part" matters: a negative z-score (an unusually quiet
    rolling mean) is not a forced-realization signal, so it's clipped to 0
    so it can't cancel an active facility on the OFFICIAL side.
    """
    if series is None:
        return None
    if not series.notna().any():
        return pd.Series(np.nan, index=series.index)
    delta = series.diff().abs()
    smoothed = delta.rolling(smooth, min_periods=max(1, smooth // 3)).mean()
    z = _freq_aware_zscore(smoothed, freq="daily")
    return z.clip(lower=0, upper=4)


def _sparse_activation_score(
    series: pd.Series,
    smooth: int = 5,
    lookback: int = TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    """Baseline-deviation score for sparse / event-driven series (H4.1 facilities).

    Phase 5 rewrite. Replaces the prior "non-zero = activated" design which
    treated 2003-2007 routine primary-credit borrowing as forced realization
    (it isn't — banks borrow at the discount window in normal times too).

    Forced realization means: facility usage is **anomalously high vs its own
    recent baseline**, not merely non-zero. We use a 252d rolling-window
    median as the baseline and rolling-std as the unit of surprise:

        log_use            = log1p(facility_level)
        baseline           = rolling_252d_median(log_use)
        spread             = rolling_252d_max(log_use) − baseline
        intensity          = clip( (log_use − baseline) / spread,  0, 1 )
        deviation_z        = (log_use − baseline) / rolling_252d_std(log_use)
        activated          = max( (deviation_z > 1.0) over last `smooth` days )
        score              = activated * (1 + 2*intensity), clipped to [0, 4]

    Output:
      0          — dormant or routine usage
      ≈ 1 - 1.5  — onset of anomaly
      ≈ 2 - 3    — full crisis-level usage (e.g. GFC peak, COVID peak)

    Days before the series' first observation remain NaN so audit code can
    distinguish "facility did not exist" from "facility existed and unused".
    """
    if not series.notna().any():
        return pd.Series(np.nan, index=series.index)
    first_obs = series.first_valid_index()
    s = series.fillna(0).clip(lower=0)
    log_use = np.log1p(s)

    min_periods = max(21, lookback // 12)
    roll = log_use.rolling(window=lookback, min_periods=min_periods)
    baseline = roll.median()
    top = roll.max()
    spread = (top - baseline).replace(0, np.nan)
    intensity = ((log_use - baseline) / spread).clip(lower=0, upper=1).fillna(0)
    intensity = intensity.rolling(smooth, min_periods=1).mean()

    std = roll.std().replace(0, np.nan)
    deviation_z = ((log_use - baseline) / std).fillna(0)
    activated = (deviation_z > 1.0).rolling(smooth, min_periods=1).max().fillna(0).astype(float)

    score = (activated * (1.0 + 2.0 * intensity)).clip(0, 4)
    if first_obs is not None:
        score = score.where(score.index >= first_obs, np.nan)
    return score


def _component(
    series: pd.Series | None,
    freq: Freq = "daily",
    smooth: int | None = None,
) -> pd.Series | None:
    """Smooth + freq-aware z-score, or sparse activation score when freq=='sparse'."""
    if series is None:
        return None
    smooth_n = smooth if smooth is not None else FREQ_SMOOTH_DEFAULT[freq]
    if freq == "sparse":
        return _sparse_activation_score(series, smooth=smooth_n)
    smoothed = series.rolling(smooth_n, min_periods=max(1, smooth_n // 3)).mean()
    return _freq_aware_zscore(smoothed, freq)


def _pct_component(
    series: pd.Series | None,
    periods: int = 63,
    smooth: int | None = None,
    freq: Freq = "daily",
) -> pd.Series | None:
    if series is None:
        return None
    return _component(series.pct_change(periods).abs(), freq=freq, smooth=smooth)


def _diff_abs(series: pd.Series | None, periods: int = 21) -> pd.Series | None:
    if series is None:
        return None
    return series.diff(periods).abs()


def _native_freq_diff_abs(
    series: pd.Series | None, freq: Freq, periods: int = 1
) -> pd.Series | None:
    """Take period-over-period absolute change on the data's native cadence.

    Daily-aligned ffill values give noisy ~0 diffs; for weekly/monthly proxies
    we resample to native cadence first, diff there, then ffill back to daily
    so the rest of the pipeline can run unchanged.
    """
    if series is None:
        return None
    if freq == "daily":
        return series.diff(periods).abs()
    rule = PANDAS_RESAMPLE_RULE[freq]
    native = series.dropna().resample(rule).last()
    if native.empty:
        return pd.Series(np.nan, index=series.index)
    delta = native.diff(periods).abs()
    max_fill = {"weekly": 7, "monthly": 35}[freq]
    return delta.reindex(series.index, method="ffill", limit=max_fill)


def _accel_abs(series: pd.Series | None, periods: int = 5) -> pd.Series | None:
    if series is None:
        return None
    return series.diff(periods).diff(periods).abs()


def _log1p_series(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    return np.log1p(series.clip(lower=0))
