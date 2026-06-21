"""Strategy definitions — baseline momentum + System overlay.

Baseline: SPY 63-day momentum.
  - momentum > 0 → long 1.0x
  - momentum ≤ 0 → cash (0.0x)

System overlay: multiply baseline position by risk gate output.
  - Baseline says long 1.0x, System says 0.5x → actual 0.5x
  - Baseline says long 1.0x, System says 0.0x → actual 0.0x
  - Baseline says cash, System is irrelevant → 0.0x

This is NOT about the System predicting direction. It's about the System
reducing size when structural conditions are hostile, even if momentum
is positive.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_momentum(close: pd.Series, lookback: int = 63) -> pd.Series:
    """Compute rolling momentum as cumulative return over lookback days.

    Args:
        close: daily close prices.
        lookback: number of trading days (default 63 ≈ 3 months).

    Returns:
        Series of momentum values (same index as close).
    """
    return close.pct_change(lookback)


def compute_baseline_position(
    close: pd.Series,
    lookback: int = 63,
) -> pd.Series:
    """Baseline strategy: long if momentum > 0, else cash.

    Returns:
        Series of position sizes (0.0 or 1.0).
    """
    mom = compute_momentum(close, lookback)
    position = (mom > 0).astype(float)
    return position


def compute_system_overlay_position(
    baseline_position: pd.Series,
    risk_position: pd.Series,
) -> pd.Series:
    """Overlay System risk gate onto baseline position.

    actual_position = baseline_position * risk_position

    If baseline says cash (0.0), System doesn't matter.
    If baseline says long (1.0), System scales it down.

    Returns:
        Series of actual position sizes.
    """
    return baseline_position * risk_position


def compute_60_40_spy_tlt_position(
    spy_close: pd.Series,
    tlt_close: pd.Series,
    spy_weight: float = 0.6,
    rebalance_freq: int = 21,
) -> pd.DataFrame:
    """60/40 SPY/TLT portfolio with periodic rebalancing.

    Args:
        spy_close: daily SPY close prices.
        tlt_close: daily TLT close prices.
        spy_weight: weight in SPY (default 0.6).
        rebalance_freq: rebalance every N trading days (default 21 ≈ monthly).

    Returns:
        DataFrame with columns: spy_position, tlt_position (target weights).
    """
    # Align on common dates
    combined = pd.DataFrame({"spy": spy_close, "tlt": tlt_close}).dropna()

    spy_pos = pd.Series(spy_weight, index=combined.index)
    tlt_pos = pd.Series(1.0 - spy_weight, index=combined.index)

    # Rebalance: on rebalance days, reset to target weights
    # Between rebalance days, let drift happen (realistic)
    rebalance_mask = pd.Series(False, index=combined.index)
    for i in range(0, len(combined), rebalance_freq):
        if i < len(combined):
            rebalance_mask.iloc[i] = True

    # On non-rebalance days, compute actual weights from drifted values
    spy_value = pd.Series(0.0, index=combined.index)
    tlt_value = pd.Series(0.0, index=combined.index)

    spy_value.iloc[0] = spy_weight
    tlt_value.iloc[0] = 1.0 - spy_weight

    for i in range(1, len(combined)):
        spy_ret = combined["spy"].iloc[i] / combined["spy"].iloc[i - 1] - 1
        tlt_ret = combined["tlt"].iloc[i] / combined["tlt"].iloc[i - 1] - 1

        spy_value.iloc[i] = spy_value.iloc[i - 1] * (1 + spy_ret)
        tlt_value.iloc[i] = tlt_value.iloc[i - 1] * (1 + tlt_ret)

        total = spy_value.iloc[i] + tlt_value.iloc[i]
        if total > 0:
            spy_pos.iloc[i] = spy_value.iloc[i] / total
            tlt_pos.iloc[i] = tlt_value.iloc[i] / total

        if rebalance_mask.iloc[i]:
            spy_value.iloc[i] = total * spy_weight
            tlt_value.iloc[i] = total * (1.0 - spy_weight)
            spy_pos.iloc[i] = spy_weight
            tlt_pos.iloc[i] = 1.0 - spy_weight

    return pd.DataFrame({"spy_position": spy_pos, "tlt_position": tlt_pos}, index=combined.index)


def compute_dynamic_lookback_position(
    close: pd.Series,
    daily_returns: pd.Series,
    low_vol_threshold: float = 0.15,
    high_vol_threshold: float = 0.18,
    low_lookback: int = 126,
    mid_lookback: int = 63,
    high_lookback: int = 21,
) -> pd.Series:
    """Momentum with dynamic lookback based on realized volatility.

    High vol → short lookback (fast response to regime change)
    Low vol → long lookback (smooth, ride trends)
    Normal vol → medium lookback (standard)

    Args:
        close: daily close prices.
        daily_returns: daily returns (for vol calculation).
        low_vol_threshold: annualized vol below which to use long lookback.
        high_vol_threshold: annualized vol above which to use short lookback.
        low_lookback/mid_lookback/high_lookback: lookback days per regime.

    Returns:
        Series of position sizes (0.0 or 1.0).
    """
    import numpy as np

    vol_20d = daily_returns.rolling(20).std() * np.sqrt(252)
    mom_low = compute_momentum(close, low_lookback)
    mom_mid = compute_momentum(close, mid_lookback)
    mom_high = compute_momentum(close, high_lookback)

    position = pd.Series(0.0, index=close.index)
    for i in range(len(close)):
        v = vol_20d.iloc[i]
        if pd.isna(v):
            continue
        elif v < low_vol_threshold:
            position.iloc[i] = 1.0 if mom_low.iloc[i] > 0 else 0.0
        elif v > high_vol_threshold:
            position.iloc[i] = 1.0 if mom_high.iloc[i] > 0 else 0.0
        else:
            position.iloc[i] = 1.0 if mom_mid.iloc[i] > 0 else 0.0
    return position


def compute_strategy_returns(
    daily_returns: pd.Series,
    position: pd.Series,
) -> pd.Series:
    """Compute strategy daily returns given a position series.

    Strategy return on day t = position on day t-1 * return on day t
    (position is known at end of previous day, applied to next day's return).

    This avoids look-ahead bias: the signal from day t determines
    the position for day t+1.
    """
    # Shift position by 1 to avoid look-ahead
    lagged_position = position.shift(1).fillna(0.0)
    return lagged_position * daily_returns
