"""Risk Gate — convert M/D/K/X readings into position sizing.

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


def compute_velocity_gate(
    signals: pd.DataFrame,
    velocity_window: int = DEFAULT_VELOCITY_WINDOW,
    velocity_threshold: float = DEFAULT_VELOCITY_THRESHOLD,
    cofire_n: int = DEFAULT_COFIRE_N,
    cofire_v: float = DEFAULT_COFIRE_V,
) -> pd.Series:
    """Compute binary velocity gate (v2, production).

    Returns 1.0 (invested) or 0.0 (cash) for each day.

    Trigger conditions (OR):
      1. Any single channel velocity > velocity_threshold over the window
      2. cofire_n+ channels have velocity > cofire_v over the window

    Args:
        signals: DataFrame with M, D, K, X columns.
        velocity_window: days to compute velocity over.
        velocity_threshold: single-channel velocity trigger.
        cofire_n: number of channels for cofire event.
        cofire_v: velocity threshold for cofire detection.

    Returns:
        Series of 1.0 or 0.0, same index as signals.
    """
    velocity = signals.diff(velocity_window)
    gate = pd.Series(1.0, index=signals.index)

    for i in range(velocity_window, len(signals)):
        vel_row = velocity.iloc[i]

        n_deteriorating = sum(
            1 for ch in ["M", "D", "K", "X"] if vel_row[ch] > cofire_v
        )
        max_vel = max(vel_row["M"], vel_row["D"], vel_row["K"], vel_row["X"])

        trigger = False
        if max_vel > velocity_threshold:
            trigger = True
        if n_deteriorating >= cofire_n:
            trigger = True

        if trigger:
            gate.iloc[i] = 0.0

    return gate


def compute_position_series(
    signals: pd.DataFrame,
    mode: str = "velocity",
    **kwargs,
) -> pd.DataFrame:
    """Compute daily position sizes from a signals DataFrame.

    Args:
        signals: DataFrame with columns M, D, K, X indexed by date.
        mode: "velocity" (default, production) or "regime" (v1 legacy).
        **kwargs: passed to the underlying gate function.

    Returns:
        DataFrame with columns: position_size, regime, action_gate,
        n_stress, n_relief, risk_flags — same index as input.
    """
    if mode == "velocity":
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
