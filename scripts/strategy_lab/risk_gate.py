"""Risk Gate — convert admitted pressure gauges into position sizing.

System role: NOT direction prediction. It answers "how much should I size?"
based on structural state.

Two gate modes:
  1. Regime gate (v1): tier-based 0.0/0.25/0.5/1.0 per regime class.
     Simple, interpretable, but too aggressive — fires on chronic elevation.
  2. Velocity gate (v2, default): binary 1.0/0.0 triggered on signal
     deterioration velocity. Fires only on genuine stress onset, not
     chronic elevation. Proven to improve Sharpe and reduce drawdown
     across multiple lookbacks and time periods.

Default velocity config (tuned via parameter sweep, 2000–2026):
  - velocity_window=20, velocity_threshold=1.5, cofire_n=3, cofire_v=0.2
  - Trigger: 20-day change in 3+ channels exceeds 0.2σ, OR any single
    channel velocity exceeds 1.5σ
  - Result: Sharpe +0.113, max DD +6.1%, return +16% (63d momentum)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# ── Regime gate thresholds (v1, backward compat) ─────────────────────
STRESS_THRESHOLD = 0.3
RELIEF_THRESHOLD = -0.3
X_STRESS_BLOCK = 0.5
CONSENSUS_MIN = 2

# ── Velocity gate defaults (v2, production) ──────────────────────────
DEFAULT_VELOCITY_WINDOW = 20
DEFAULT_VELOCITY_THRESHOLD = 1.5
DEFAULT_COFIRE_N = 3
DEFAULT_COFIRE_V = 0.2

# Bull-market "don't disturb" modulation (validated via cost sweep)
DEFAULT_BULL_MOM_LOOKBACK = 63
DEFAULT_BULL_VOL_LOOKBACK = 21
DEFAULT_BULL_VOL_CEILING = 0.15  # 21d realized ann. vol
DEFAULT_BULL_VELOCITY_THRESHOLD = 2.0


@dataclass
class RiskState:
    """Per-day risk gate output (regime gate v1)."""
    position_size: float
    regime: str
    action_gate: str
    n_stress: int
    n_relief: int
    risk_flags: list[str]


def classify_channel(value: float | None) -> str:
    """Classify a single channel reading."""
    if value is None or np.isnan(value):
        return "unknown"
    if value > STRESS_THRESHOLD:
        return "stress"
    if value < RELIEF_THRESHOLD:
        return "relief"
    return "neutral"


def evaluate_day(M: float, D: float, K: float, X: float) -> RiskState:
    """Evaluate structural risk for a single day (regime gate v1).

    Kept for backward compatibility and interpretability.
    For production backtesting, use compute_position_series() which
    defaults to the velocity gate.
    """
    signals = {"M": M, "D": D, "K": K, "X": X}
    classifications = {ch: classify_channel(v) for ch, v in signals.items()}

    n_stress = sum(1 for c in classifications.values() if c == "stress")
    n_relief = sum(1 for c in classifications.values() if c == "relief")

    risk_flags: list[str] = []

    x_stress = not np.isnan(X) and X > X_STRESS_BLOCK
    k_stress = not np.isnan(K) and K > STRESS_THRESHOLD

    if x_stress and k_stress:
        regime = "STRUCTURAL_STRESS"
    elif x_stress:
        regime = "LEVERAGE_STRESS"
    elif k_stress:
        regime = "CURVATURE_STRESS"
    elif n_relief >= 3:
        regime = "ALL_CLEAR"
    elif n_stress >= 3:
        regime = "DIFFUSE_STRESS"
    elif n_stress >= 2 and n_relief >= 1:
        regime = "MIXED"
    else:
        regime = "NEUTRAL"

    if regime == "STRUCTURAL_STRESS":
        position_size = 0.0
        action_gate = "NO_TRADE"
        risk_flags.append("Structural stress: X and K both elevated")
    elif regime == "LEVERAGE_STRESS":
        position_size = 0.0
        action_gate = "NO_TRADE"
        risk_flags.append(f"Leverage stress: X={X:.2f}")
    elif regime in ("DIFFUSE_STRESS", "MIXED"):
        position_size = 0.25
        action_gate = "STRESS"
        risk_flags.append(f"Regime: {regime}")
    elif n_stress >= 1:
        position_size = 0.5
        action_gate = "OBSERVE"
        stressed = [ch for ch, c in classifications.items() if c == "stress"]
        risk_flags.append(f"Stress in: {', '.join(stressed)}")
    elif regime == "ALL_CLEAR":
        position_size = 1.0
        action_gate = "FULL"
    else:
        position_size = 1.0
        action_gate = "FULL"

    return RiskState(
        position_size=position_size,
        regime=regime,
        action_gate=action_gate,
        n_stress=n_stress,
        n_relief=n_relief,
        risk_flags=risk_flags,
    )


def bull_relaxed_threshold_series(
    close: pd.Series,
    *,
    base_threshold: float = DEFAULT_VELOCITY_THRESHOLD,
    bull_threshold: float = DEFAULT_BULL_VELOCITY_THRESHOLD,
    mom_lookback: int = DEFAULT_BULL_MOM_LOOKBACK,
    vol_lookback: int = DEFAULT_BULL_VOL_LOOKBACK,
    vol_ceiling: float = DEFAULT_BULL_VOL_CEILING,
) -> pd.Series:
    """Raise velocity threshold in calm bull regimes.

    Condition: 63d momentum > 0 AND 21d realized annualized vol < 15%.
    When true, use bull_threshold (default 2.0); else base_threshold (1.5).
    """
    mom = close / close.shift(mom_lookback) - 1.0
    rets = close.pct_change()
    ann_vol = rets.rolling(vol_lookback).std() * np.sqrt(252)
    relaxed = (mom > 0) & (ann_vol < vol_ceiling)
    values = np.where(relaxed.fillna(False), bull_threshold, base_threshold)
    return pd.Series(values, index=close.index, dtype=float)


def compute_velocity_gate(
    signals: pd.DataFrame,
    velocity_window: int = DEFAULT_VELOCITY_WINDOW,
    velocity_threshold: float = DEFAULT_VELOCITY_THRESHOLD,
    cofire_n: int = DEFAULT_COFIRE_N,
    cofire_v: float = DEFAULT_COFIRE_V,
    *,
    close: pd.Series | None = None,
    bull_modulation: bool = False,
    bull_velocity_threshold: float = DEFAULT_BULL_VELOCITY_THRESHOLD,
    bull_mom_lookback: int = DEFAULT_BULL_MOM_LOOKBACK,
    bull_vol_lookback: int = DEFAULT_BULL_VOL_LOOKBACK,
    bull_vol_ceiling: float = DEFAULT_BULL_VOL_CEILING,
) -> pd.Series:
    """Compute binary velocity gate (v2, production).

    Returns 1.0 (invested) or 0.0 (cash) for each day.

    Trigger conditions (OR):
      1. Any single channel velocity > day threshold over the window
      2. cofire_n+ channels have velocity > cofire_v over the window

    When bull_modulation=True and ``close`` is provided, the single-channel
    threshold is raised to ``bull_velocity_threshold`` on calm bull days
    (63d mom > 0 and 21d ann. vol < bull_vol_ceiling).
    """
    signal_columns = [column for column in signals.columns if pd.api.types.is_numeric_dtype(signals[column])]
    if not signal_columns:
        raise ValueError("velocity gate requires at least one numeric pressure gauge")
    velocity = signals[signal_columns].diff(velocity_window)
    gate = pd.Series(1.0, index=signals.index)

    thresholds = pd.Series(float(velocity_threshold), index=signals.index)
    if bull_modulation and close is not None:
        aligned_close = close.reindex(signals.index)
        thresholds = bull_relaxed_threshold_series(
            aligned_close,
            base_threshold=velocity_threshold,
            bull_threshold=bull_velocity_threshold,
            mom_lookback=bull_mom_lookback,
            vol_lookback=bull_vol_lookback,
            vol_ceiling=bull_vol_ceiling,
        )

    for i in range(velocity_window, len(signals)):
        vel_row = velocity.iloc[i]

        n_deteriorating = sum(1 for ch in signal_columns if vel_row[ch] > cofire_v)
        max_vel = max(float(vel_row[ch]) for ch in signal_columns)
        day_threshold = float(thresholds.iloc[i])

        trigger = False
        if max_vel > day_threshold:
            trigger = True
        if n_deteriorating >= cofire_n:
            trigger = True

        if trigger:
            gate.iloc[i] = 0.0

    return gate


def compute_position_series(
    signals: pd.DataFrame,
    mode: str = "velocity",
    close: pd.Series | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Compute daily position sizes from a signals DataFrame.

    Args:
        signals: DataFrame of admitted numeric pressure gauges indexed by date.
        mode: "velocity" (default, production) or "regime" (v1 legacy).
        close: optional price series for bull-market modulation.
        **kwargs: passed to the underlying gate function.
    """
    if mode == "velocity":
        if close is not None and "close" not in kwargs:
            kwargs["close"] = close
        gate = compute_velocity_gate(signals, **kwargs)
        rows = []
        for date, pos in gate.items():
            rows.append({
                "date": date,
                "position_size": float(pos),
                "regime": "VELOCITY_TRIGGER" if pos < 1.0 else "CALM",
                "action_gate": "EXIT" if pos < 1.0 else "FULL",
                "n_stress": 0,
                "n_relief": 0,
                "risk_flags": "velocity_deterioration" if pos < 1.0 else "",
            })
        return pd.DataFrame(rows).set_index("date")
    else:
        # Legacy regime gate
        rows = []
        for date, row in signals.iterrows():
            state = evaluate_day(row["M"], row["D"], row["K"], row["X"])
            rows.append({
                "date": date,
                "position_size": state.position_size,
                "regime": state.regime,
                "action_gate": state.action_gate,
                "n_stress": state.n_stress,
                "n_relief": state.n_relief,
                "risk_flags": "|".join(state.risk_flags) if state.risk_flags else "",
            })
        return pd.DataFrame(rows).set_index("date")


def latest_velocity_gate_state(signals: pd.DataFrame | None = None) -> dict:
    """Resolve today's velocity gate as FULL / EXIT for recording only.

    Prefers today's shadow card when present; otherwise computes from signals.
    Does not authorize or block any trade decision.
    """
    from scripts import _runtime_io as rio

    shadow_path = rio.ROOT / "Output" / "strategy_lab" / "shadow_cards" / "latest.json"
    shadow = rio.load_json(shadow_path) if shadow_path.exists() else None
    if isinstance(shadow, dict) and shadow.get("velocity_gate") is not None:
        rec = shadow.get("recommendation") or {}
        vg = shadow.get("velocity_gate") or {}
        state = rec.get("sizing_label")
        if state not in ("FULL", "EXIT"):
            pos = float(vg.get("position", 1.0) or 1.0)
            state = "EXIT" if pos < 1.0 else "FULL"
        velocity_20d = vg.get("velocity_20d")
        n_deteriorating = None
        if isinstance(velocity_20d, dict):
            n_deteriorating = sum(
                1
                for ch in velocity_20d
                if float(velocity_20d.get(ch, 0) or 0) > DEFAULT_COFIRE_V
            )
        return {
            "state": state,
            "position": float(vg.get("position", 1.0 if state == "FULL" else 0.0) or 0.0),
            "trigger": bool(vg.get("trigger", state == "EXIT")),
            "trigger_reason": vg.get("trigger_reason") or rec.get("primary_reason"),
            "velocity_20d": velocity_20d,
            "n_deteriorating": n_deteriorating,
            "source": "shadow_card",
            "as_of_date": shadow.get("as_of_date"),
        }

    if signals is None:
        from scripts.strategy_lab.data_loader import load_signals

        signals = load_signals()
    if signals is None or signals.empty:
        return {
            "state": "UNKNOWN",
            "position": None,
            "trigger": None,
            "trigger_reason": "No signal data",
            "velocity_20d": None,
            "n_deteriorating": None,
            "source": "unavailable",
            "as_of_date": None,
        }

    gate = compute_velocity_gate(signals)
    position = float(gate.iloc[-1])
    state = "EXIT" if position < 1.0 else "FULL"
    as_of = signals.index[-1]
    as_of_date = str(as_of.date()) if hasattr(as_of, "date") else str(as_of)[:10]
    velocity = signals.diff(DEFAULT_VELOCITY_WINDOW)
    vel_row = velocity.iloc[-1]
    velocity_20d = {ch: float(vel_row[ch]) for ch in signals.columns if ch in vel_row.index}
    n_deteriorating = sum(
        1
        for ch in signals.columns
        if ch in vel_row.index and float(vel_row[ch]) > DEFAULT_COFIRE_V
    )
    return {
        "state": state,
        "position": position,
        "trigger": state == "EXIT",
        "trigger_reason": "velocity_deterioration" if state == "EXIT" else "No structural stress detected",
        "velocity_20d": velocity_20d,
        "n_deteriorating": n_deteriorating,
        "source": "compute_velocity_gate",
        "as_of_date": as_of_date,
    }
