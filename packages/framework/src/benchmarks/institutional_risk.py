from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


RISK_STATE_ORDER = ["NORMAL", "WATCH", "RISK_OFF", "CRISIS"]


@dataclass(frozen=True)
class RiskPolicy:
    watch_enter: float = 1.0
    risk_off_enter: float = 1.5
    crisis_enter: float = 2.5
    exit_buffer: float = 0.35
    confirmation_window: int = 3
    confirmation_count: int = 2
    ewma_span: int = 4


DEFAULT_RISK_POLICY = RiskPolicy()


def rolling_robust_zscore(series: pd.Series, window: int = 52, min_periods: int = 26) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    median = numeric.rolling(window=window, min_periods=min_periods).median().shift(1)
    mad = numeric.rolling(window=window, min_periods=min_periods).apply(_mad, raw=False).shift(1)
    fallback_scale = numeric.rolling(window=window, min_periods=min_periods).std(ddof=0).shift(1)
    scale = (1.4826 * mad).where(mad > 0.0, fallback_scale).replace(0.0, np.nan)
    z = (numeric - median) / scale
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def ewma_signal(series: pd.Series, span: int = 4) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").ewm(span=span, adjust=False, min_periods=1).mean()


def persistent_threshold(series: pd.Series, threshold: float, window: int = 3, count: int = 2) -> pd.Series:
    hits = pd.to_numeric(series, errors="coerce").ge(threshold).astype(int)
    return hits.rolling(window=window, min_periods=1).sum().ge(count)


def state_machine(series: pd.Series, policy: RiskPolicy = DEFAULT_RISK_POLICY) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    watch_confirmed = persistent_threshold(values, policy.watch_enter, policy.confirmation_window, policy.confirmation_count)
    risk_confirmed = persistent_threshold(values, policy.risk_off_enter, policy.confirmation_window, policy.confirmation_count)
    crisis_confirmed = persistent_threshold(values, policy.crisis_enter, policy.confirmation_window, policy.confirmation_count)

    state = "NORMAL"
    states: list[str] = []
    for idx, value in values.items():
        if bool(crisis_confirmed.loc[idx]):
            state = "CRISIS"
        elif bool(risk_confirmed.loc[idx]) and _state_rank(state) < _state_rank("RISK_OFF"):
            state = "RISK_OFF"
        elif bool(watch_confirmed.loc[idx]) and _state_rank(state) < _state_rank("WATCH"):
            state = "WATCH"
        elif state == "CRISIS" and value < policy.crisis_enter - policy.exit_buffer:
            state = "RISK_OFF" if value >= policy.risk_off_enter - policy.exit_buffer else "WATCH"
        elif state == "RISK_OFF" and value < policy.risk_off_enter - policy.exit_buffer:
            state = "WATCH" if value >= policy.watch_enter - policy.exit_buffer else "NORMAL"
        elif state == "WATCH" and value < policy.watch_enter - policy.exit_buffer:
            state = "NORMAL"
        states.append(state)
    return pd.Series(states, index=values.index, name=f"{series.name or 'signal'}_state")


def action_tier(states: pd.Series) -> pd.Series:
    mapping = {
        "NORMAL": "Monitor",
        "WATCH": "Research review",
        "RISK_OFF": "Unvalidated timing-research warning",
        "CRISIS": "Stress classification review",
    }
    return states.map(mapping).fillna("Monitor")


def apply_risk_policy(signals: pd.DataFrame, columns: list[str], policy: RiskPolicy = DEFAULT_RISK_POLICY) -> pd.DataFrame:
    out = signals.copy()
    for col in columns:
        if col not in out.columns:
            continue
        smooth_col = f"{col}_ewma"
        state_col = f"{col}_state"
        action_col = f"{col}_action"
        out[smooth_col] = ewma_signal(out[col], span=policy.ewma_span)
        out[state_col] = state_machine(out[smooth_col].rename(col), policy=policy)
        out[action_col] = action_tier(out[state_col])
    return out


def _mad(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return float("nan")
    med = clean.median()
    return float((clean - med).abs().median())


def _state_rank(state: str) -> int:
    try:
        return RISK_STATE_ORDER.index(state)
    except ValueError:
        return 0


def max_state(states: pd.Series) -> str:
    if states.empty:
        return "NORMAL"
    return max((str(state) for state in states.dropna()), key=_state_rank, default="NORMAL")
