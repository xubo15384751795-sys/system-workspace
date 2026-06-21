"""Continuous Risk Gate — smooth position scaling instead of hard tiers.

Instead of binary 0.0/0.25/0.5/1.0 per regime, this gate computes a
continuous multiplier based on the actual channel readings:

    stress_level = max(0, max(stress_channels) - threshold) / scale
    position = max(floor, 1.0 - stress_level)

This means:
  - Mild stress (one channel at 0.35): position ≈ 0.95x (barely noticeable)
  - Moderate stress (one channel at 0.8): position ≈ 0.6x
  - Severe stress (one channel at 1.5): position ≈ 0.0x

The key insight: continuous scaling stays invested most of the time,
only scaling down proportionally to stress severity. This preserves
more return while still reducing exposure during genuine stress.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def continuous_position(
    M: float,
    D: float,
    K: float,
    X: float,
    threshold: float = 0.3,
    scale: float = 1.0,
    floor: float = 0.0,
    x_weight: float = 1.5,
    m_weight: float = 1.0,
    d_weight: float = 1.0,
    k_weight: float = 0.8,
) -> float:
    """Compute continuous position size from channel readings.

    Args:
        M, D, K, X: channel z-scores.
        threshold: stress onset threshold (channels below this = no stress).
        scale: how quickly position drops (higher = more aggressive).
        floor: minimum position (0.0 = can go to full cash).
        x_weight: extra weight for X channel (leverage stress is most dangerous).
        m_weight, d_weight, k_weight: per-channel weights.

    Returns:
        Position size in [floor, 1.0].
    """
    # Weighted stress contributions (only positive excess matters)
    stress_M = max(0, M - threshold) * m_weight
    stress_D = max(0, D - threshold) * d_weight
    stress_K = max(0, K - threshold) * k_weight
    stress_X = max(0, X - threshold) * x_weight

    # Also penalize extreme negative values (too much relief can mean complacency)
    # But much less aggressively
    relief_penalty = 0.0
    for v in [M, D, K, X]:
        if v < -1.5:
            relief_penalty = max(relief_penalty, abs(v + 1.5) * 0.1)

    # Combined stress level
    max_stress = max(stress_M, stress_D, stress_K, stress_X)
    combined_stress = max_stress + relief_penalty

    # Map to position
    position = max(floor, 1.0 - combined_stress / scale)

    return round(position, 4)


def compute_continuous_positions(
    signals: pd.DataFrame,
    threshold: float = 0.3,
    scale: float = 1.0,
    floor: float = 0.0,
    x_weight: float = 1.5,
    m_weight: float = 1.0,
    d_weight: float = 1.0,
    k_weight: float = 0.8,
) -> pd.Series:
    """Compute continuous position series from signal DataFrame."""
    positions = []
    for _, row in signals.iterrows():
        pos = continuous_position(
            row["M"], row["D"], row["K"], row["X"],
            threshold=threshold, scale=scale, floor=floor,
            x_weight=x_weight, m_weight=m_weight,
            d_weight=d_weight, k_weight=k_weight,
        )
        positions.append(pos)
    return pd.Series(positions, index=signals.index)


def sweep_continuous(
    data: pd.DataFrame,
    lookback: int = 63,
) -> list[dict]:
    """Sweep continuous gate parameters."""
    from strategy_lab.backtest import compute_metrics
    from strategy_lab.strategies import compute_baseline_position

    daily_returns = data["return_1d"]
    baseline_pos = compute_baseline_position(data["close"], lookback=lookback)
    signals = data[["M", "D", "K", "X"]]

    # Baseline metrics
    baseline_ret = daily_returns * baseline_pos.shift(1).fillna(0)
    baseline_m = compute_metrics(baseline_ret, baseline_pos, "baseline")

    # ── Sweep grid ───────────────────────────────────────────────────
    results = []

    for threshold in [0.2, 0.3, 0.4, 0.5]:
        for scale in [0.8, 1.0, 1.2, 1.5, 2.0]:
            for floor in [0.0, 0.1, 0.2]:
                for x_weight in [1.0, 1.5, 2.0]:
                    risk_pos = compute_continuous_positions(
                        signals,
                        threshold=threshold,
                        scale=scale,
                        floor=floor,
                        x_weight=x_weight,
                    )
                    overlay_pos = baseline_pos * risk_pos
                    overlay_ret = daily_returns * overlay_pos.shift(1).fillna(0)
                    m = compute_metrics(overlay_ret, overlay_pos, "overlay")

                    results.append({
                        "config": f"t={threshold}|s={scale}|f={floor}|xw={x_weight}",
                        "threshold": threshold,
                        "scale": scale,
                        "floor": floor,
                        "x_weight": x_weight,
                        "total_return": float(m.total_return),
                        "ann_return": float(m.ann_return),
                        "sharpe": float(m.sharpe),
                        "max_drawdown": float(m.max_drawdown),
                        "calmar": float(m.calmar),
                        "tail_loss_5pct": float(m.tail_loss_5pct),
                        "time_in_market": float(m.time_in_market),
                        "return_delta": float(m.total_return - baseline_m.total_return),
                        "sharpe_delta": float(m.sharpe - baseline_m.sharpe),
                        "dd_delta": float(m.max_drawdown - baseline_m.max_drawdown),
                        "calmar_delta": float(m.calmar - baseline_m.calmar),
                        "tail_delta": float(m.tail_loss_5pct - baseline_m.tail_loss_5pct),
                    })

    return results


def rank_continuous(results: list[dict], baseline: dict) -> list[dict]:
    """Rank by composite score balancing Sharpe, DD improvement, return preservation."""
    for r in results:
        dd_improve = r["dd_delta"]  # positive = better
        tail_improve = r["tail_delta"]  # positive = better
        return_preserved = 1.0 + r["return_delta"] / max(abs(baseline["total_return"]), 0.01)

        # Score: Sharpe improvement + DD improvement scaled + return preservation
        r["score"] = (
            r["sharpe"]
            + 0.3 * (dd_improve / 0.05)
            + 0.2 * (tail_improve / 0.001)
            + 0.3 * max(0, return_preserved)  # reward return preservation
        )

    return sorted(results, key=lambda r: r.get("score", 0), reverse=True)
