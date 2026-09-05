from __future__ import annotations

import numpy as np
import pandas as pd


def build_forward_targets(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    equity = _first(frame, ("SPY", "SP500", "SPX", "close", "equity_index"))
    vol = _first(frame, ("VIXCLS", "VIX", "realized_vol"))
    credit = _first(frame, ("BAMLH0A0HYM2", "BAA10Y", "credit_spread"))
    liquidity = _first(frame, ("NFCI", "STLFSI4", "liquidity_stress"))

    for horizon in (5, 20, 60):
        out[f"forward_{horizon}d_equity_drawdown"] = _forward_drawdown(equity, horizon)
        out[f"forward_{horizon}d_realized_vol_spike"] = _forward_change(vol, horizon)
    if credit is not None:
        out["forward_20d_credit_stress_widening"] = _forward_change(credit, 20)
    if liquidity is not None:
        out["forward_20d_liquidity_stress_widening"] = _forward_change(liquidity, 20)
    return out


def make_binary_targets(targets: pd.DataFrame, quantile: float = 0.8, min_periods: int = 60) -> pd.DataFrame:
    out = pd.DataFrame(index=targets.index)
    for col in targets.columns:
        threshold = targets[col].rolling(252, min_periods=min_periods).quantile(quantile).shift(1)
        out[col] = pd.to_numeric(targets[col], errors="coerce").gt(threshold).fillna(False)
    return out


def _first(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series | None:
    for col in columns:
        if col in frame.columns:
            return pd.to_numeric(frame[col], errors="coerce")
    return None


def _forward_drawdown(price: pd.Series | None, horizon: int) -> pd.Series:
    if price is None:
        return pd.Series(np.nan)
    future_min = price.shift(-1).rolling(horizon, min_periods=1).min().shift(-(horizon - 1))
    return ((price - future_min) / price.replace(0.0, np.nan)).clip(lower=0.0)


def _forward_change(series: pd.Series | None, horizon: int) -> pd.Series:
    if series is None:
        return pd.Series(np.nan)
    future_max = series.shift(-1).rolling(horizon, min_periods=1).max().shift(-(horizon - 1))
    return (future_max - series).clip(lower=0.0)
