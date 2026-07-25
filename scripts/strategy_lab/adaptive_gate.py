"""Adaptive Risk Gate — channel-specific thresholds calibrated to actual distributions.

Core insight from data analysis (2000–2026):
  M: mean=0.08, std=1.34  → threshold should be ~0.8 (top 33%)
  D: mean=0.16, std=1.20  → threshold should be ~0.8 (top 30%)
  K: mean=0.07, std=0.93  → threshold should be ~0.7 (top 20%)
  X: mean=0.51, std=0.77  → threshold should be ~1.2 (top 23%)

The original gate used a flat 0.3 threshold for all channels.
With X > 0.3 being true 59% of the time, the gate was almost always on.

This gate uses:
  1. Channel-specific stress thresholds (tuned to fire on top ~25% of days)
  2. Continuous scaling above threshold (not binary)
  3. Combined stress from multiple channels (multiplicative, not just max)
  4. A floor to prevent complete cash-out except in true crises

Usage:
    from scripts.strategy_lab.adaptive_gate import compute_adaptive_positions
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── Channel-specific thresholds ──────────────────────────────────────
# Calibrated so each channel triggers "stress" on roughly the top 25-30%
# of its distribution. This means the gate activates when a channel is
# genuinely elevated relative to its own history, not on noise.
DEFAULT_THRESHOLDS = {
    "M": 0.8,   # M > 0.8 on ~30% of days
    "D": 0.8,   # D > 0.8 on ~28% of days
    "K": 0.7,   # K > 0.7 on ~20% of days
    "X": 1.2,   # X > 1.2 on ~15% of days (X is most persistent)
}

# Per-channel weights for combined stress score
DEFAULT_WEIGHTS = {
    "M": 0.8,   # anchor mismatch — important but noisy
    "D": 0.9,   # path feasibility — strong signal
    "K": 0.6,   # curvature — measurement-incomplete, lower weight
    "X": 1.0,   # shadow accumulation — most dangerous when elevated
}


def adaptive_position(
    M: float,
    D: float,
    K: float,
    X: float,
    thresholds: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
    scale: float = 2.0,
    floor: float = 0.1,
    crisis_floor: float = 0.0,
    crisis_threshold: float = 2.0,
) -> float:
    """Compute adaptive position size from channel readings.

    Args:
        M, D, K, X: channel z-scores.
        thresholds: per-channel stress onset thresholds.
        weights: per-channel importance weights.
        scale: how quickly position drops above threshold.
        floor: normal minimum position (prevents full cash except crisis).
        crisis_floor: position during crisis (when any channel > crisis_threshold).
        crisis_threshold: level that triggers crisis mode.

    Returns:
        Position size in [crisis_floor, 1.0].
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    if weights is None:
        weights = DEFAULT_WEIGHTS

    channels = {"M": M, "D": D, "K": K, "X": X}

    # Check for crisis (any channel extremely elevated)
    max_raw = max(abs(v) for v in channels.values())
    if max_raw > crisis_threshold:
        # Crisis: check if it's stress (positive) or relief (negative)
        max_stress = max(v for v in channels.values())
        if max_stress > crisis_threshold:
            return crisis_floor

    # Compute per-channel stress contributions
    stress_scores = []
    for ch, value in channels.items():
        t = thresholds.get(ch, 0.5)
        w = weights.get(ch, 1.0)
        excess = max(0, value - t)
        stress_scores.append(excess * w)

    # Combined stress: root-mean-square (penalizes multiple channels)
    if any(s > 0 for s in stress_scores):
        rms_stress = np.sqrt(np.mean([s ** 2 for s in stress_scores]))
    else:
        rms_stress = 0.0

    # Map to position
    position = max(floor, 1.0 - rms_stress / scale)

    return round(float(position), 4)


def compute_adaptive_positions(
    signals: pd.DataFrame,
    thresholds: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
    scale: float = 2.0,
    floor: float = 0.1,
    crisis_floor: float = 0.0,
    crisis_threshold: float = 2.0,
) -> pd.Series:
    """Compute adaptive position series from signal DataFrame."""
    positions = []
    for _, row in signals.iterrows():
        pos = adaptive_position(
            row["M"], row["D"], row["K"], row["X"],
            thresholds=thresholds, weights=weights,
            scale=scale, floor=floor,
            crisis_floor=crisis_floor, crisis_threshold=crisis_threshold,
        )
        positions.append(pos)
    return pd.Series(positions, index=signals.index)


def sweep_adaptive(
    data: pd.DataFrame,
    lookback: int = 63,
) -> list[dict]:
    """Sweep adaptive gate parameters."""
    from scripts.strategy_lab.backtest import compute_metrics
    from scripts.strategy_lab.strategies import compute_baseline_position

    daily_returns = data["return_1d"]
    baseline_pos = compute_baseline_position(data["close"], lookback=lookback)
    signals = data[["M", "D", "K", "X"]]

    # Baseline metrics
    baseline_ret = daily_returns * baseline_pos.shift(1).fillna(0)
    baseline_m = compute_metrics(baseline_ret, baseline_pos, "baseline")
    baseline_dict = baseline_m.to_dict()

    results = []

    # Sweep key parameters
    for x_thresh in [0.8, 1.0, 1.2, 1.5, 2.0]:
        for m_thresh in [0.5, 0.8, 1.0, 1.2]:
            for scale in [1.5, 2.0, 2.5, 3.0]:
                for floor in [0.0, 0.1, 0.2]:
                    thresholds = {"M": m_thresh, "D": m_thresh, "K": 0.7, "X": x_thresh}
                    risk_pos = compute_adaptive_positions(
                        signals, thresholds=thresholds,
                        scale=scale, floor=floor,
                    )
                    overlay_pos = baseline_pos * risk_pos
                    overlay_ret = daily_returns * overlay_pos.shift(1).fillna(0)
                    m = compute_metrics(overlay_ret, overlay_pos, "overlay")

                    results.append({
                        "config": f"x={x_thresh}|m={m_thresh}|s={scale}|f={floor}",
                        "x_thresh": x_thresh,
                        "m_thresh": m_thresh,
                        "scale": scale,
                        "floor": floor,
                        "total_return": float(m.total_return),
                        "ann_return": float(m.ann_return),
                        "sharpe": float(m.sharpe),
                        "max_drawdown": float(m.max_drawdown),
                        "calmar": float(m.calmar),
                        "tail_loss_5pct": float(m.tail_loss_5pct),
                        "time_in_market": float(m.time_in_market),
                        "avg_position": float(m.time_in_market),  # approx
                        "return_delta": float(m.total_return - baseline_dict["total_return"]),
                        "sharpe_delta": float(m.sharpe - baseline_dict["sharpe"]),
                        "dd_delta": float(m.max_drawdown - baseline_dict["max_drawdown"]),
                        "calmar_delta": float(m.calmar - baseline_dict["calmar"]),
                        "tail_delta": float(m.tail_loss_5pct - baseline_dict["tail_loss_5pct"]),
                    })

    return results
