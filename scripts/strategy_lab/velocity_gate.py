"""Velocity Risk Gate — triggers on rapid deterioration, not absolute levels.

Core insight: M/D/K/X channels are frequently elevated (X > 0.3 on 59%
of days). Using absolute thresholds fires too often and kills returns.

Instead, this gate triggers on:
  1. RAPID DETERIORATION: channel jumped significantly in 5/10 days
  2. EXTREME LEVELS: channel at historical extreme (>2.0σ)
  3. MULTIPLE CHANNELS MOVING TOGETHER: correlated stress onset

This preserves the "stay invested in normal times" behavior while
catching the genuine stress episodes that precede drawdowns.

Usage:
    from scripts.strategy_lab.velocity_gate import compute_velocity_positions
"""
from __future__ import annotations

import pandas as pd


def compute_velocity_positions(
    signals: pd.DataFrame,
    velocity_window: int = 5,
    velocity_threshold: float = 0.5,
    extreme_threshold: float = 2.0,
    cofire_threshold: int = 2,
    cofire_velocity: float = 0.3,
    scale: float = 1.5,
    floor: float = 0.2,
    crisis_floor: float = 0.0,
) -> pd.Series:
    """Compute position sizes based on signal velocity and extremes.

    Triggers position reduction when:
      - Any channel velocity > velocity_threshold (rapid deterioration)
      - Any channel > extreme_threshold (extreme level)
      - cofire_threshold+ channels moving in same direction at velocity > cofire_velocity

    Args:
        signals: DataFrame with M, D, K, X columns.
        velocity_window: days to compute velocity over.
        velocity_threshold: single-channel velocity that triggers reduction.
        extreme_threshold: absolute level that triggers reduction.
        cofire_threshold: number of channels needed for cofire event.
        cofire_velocity: velocity threshold for cofire detection.
        scale: how quickly position drops with velocity.
        floor: normal minimum position.
        crisis_floor: position during extreme events.

    Returns:
        Series of position sizes.
    """
    # Compute per-channel velocity (change over window)
    velocity = signals.diff(velocity_window)

    positions = pd.Series(1.0, index=signals.index)

    for i in range(velocity_window, len(signals)):
        pos = 1.0
        reasons = []

        # ── Check extreme levels ─────────────────────────────────────
        row = signals.iloc[i]
        max_level = max(abs(row["M"]), abs(row["D"]), abs(row["K"]), abs(row["X"]))
        if max_level > extreme_threshold:
            # Only reduce if it's stress (positive), not relief
            max_stress = max(row["M"], row["D"], row["K"], row["X"])
            if max_stress > extreme_threshold:
                pos = min(pos, crisis_floor)
                reasons.append("extreme_level")

        # ── Check single-channel velocity ────────────────────────────
        vel_row = velocity.iloc[i]
        max_velocity = 0.0
        for ch in ["M", "D", "K", "X"]:
            v = vel_row[ch]
            if v > velocity_threshold:
                max_velocity = max(max_velocity, v)

        if max_velocity > velocity_threshold:
            # Scale position down based on velocity severity
            vel_factor = min(1.0, (max_velocity - velocity_threshold) / scale)
            pos = min(pos, max(floor, 1.0 - vel_factor))
            reasons.append(f"velocity={max_velocity:.2f}")

        # ── Check cofire (multiple channels deteriorating together) ──
        n_deteriorating = sum(
            1 for ch in ["M", "D", "K", "X"]
            if vel_row[ch] > cofire_velocity
        )
        if n_deteriorating >= cofire_threshold:
            cofire_factor = min(1.0, (n_deteriorating - cofire_threshold + 1) * 0.3)
            pos = min(pos, max(floor, 1.0 - cofire_factor))
            reasons.append(f"cofire={n_deteriorating}")

        positions.iloc[i] = round(pos, 4)

    return positions


def sweep_velocity(
    data: pd.DataFrame,
    lookback: int = 63,
) -> list[dict]:
    """Sweep velocity gate parameters."""
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

    for vel_window in [3, 5, 10]:
        for vel_thresh in [0.3, 0.5, 0.7, 1.0]:
            for extreme in [1.5, 2.0, 2.5]:
                for scale in [1.0, 1.5, 2.0]:
                    for floor in [0.0, 0.1, 0.2]:
                        risk_pos = compute_velocity_positions(
                            signals,
                            velocity_window=vel_window,
                            velocity_threshold=vel_thresh,
                            extreme_threshold=extreme,
                            scale=scale,
                            floor=floor,
                        )
                        overlay_pos = baseline_pos * risk_pos
                        overlay_ret = daily_returns * overlay_pos.shift(1).fillna(0)
                        m = compute_metrics(overlay_ret, overlay_pos, "overlay")

                        results.append({
                            "config": f"vw={vel_window}|vt={vel_thresh}|ext={extreme}|s={scale}|f={floor}",
                            "vel_window": vel_window,
                            "vel_thresh": vel_thresh,
                            "extreme": extreme,
                            "scale": scale,
                            "floor": floor,
                            "total_return": float(m.total_return),
                            "ann_return": float(m.ann_return),
                            "sharpe": float(m.sharpe),
                            "max_drawdown": float(m.max_drawdown),
                            "calmar": float(m.calmar),
                            "tail_loss_5pct": float(m.tail_loss_5pct),
                            "time_in_market": float(m.time_in_market),
                            "return_delta": float(m.total_return - baseline_dict["total_return"]),
                            "sharpe_delta": float(m.sharpe - baseline_dict["sharpe"]),
                            "dd_delta": float(m.max_drawdown - baseline_dict["max_drawdown"]),
                            "calmar_delta": float(m.calmar - baseline_dict["calmar"]),
                            "tail_delta": float(m.tail_loss_5pct - baseline_dict["tail_loss_5pct"]),
                        })

    return results
