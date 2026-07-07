from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StructuralVulnerabilitySignal:
    score: pd.Series
    horizon: str = "3-18m"
    claim_boundary: str = "Slow-moving fragility signal; not a trading or timing signal."
    target_family: tuple[str, ...] = ("3m_vulnerability", "6m_vulnerability", "18m_vulnerability")


@dataclass(frozen=True)
class ActionableTransitionSignal:
    score: pd.Series
    horizon: str = "5d/20d/60d"
    claim_boundary: str = "Timing research only after rolling-origin OOS validation."
    max_successful_warning_days: int = 120
    target_family: tuple[str, ...] = ("5d_forward_stress", "20d_forward_stress", "60d_forward_stress")


def structural_vulnerability_signal(channels: pd.DataFrame, window: int = 63) -> StructuralVulnerabilitySignal:
    required = _channel_frame(channels)
    slow = required.rolling(window=window, min_periods=1).mean()
    score = slow[["M", "D_contraction", "K", "X"]].mean(axis=1).rename("structural_vulnerability")
    return StructuralVulnerabilitySignal(score=score)


def actionable_transition_signal(
    channels: pd.DataFrame,
    threshold: float = 1.0,
    persistence: int = 3,
) -> ActionableTransitionSignal:
    required = _channel_frame(channels)
    joint = required[["M", "D_contraction", "K", "X"]].mean(axis=1)
    change = joint.diff().clip(lower=0.0)
    acceleration = joint.diff().diff().clip(lower=0.0)
    crossing = joint.ge(threshold) & joint.shift(1).lt(threshold)
    persistent = joint.ge(threshold).rolling(persistence, min_periods=1).sum().ge(persistence)
    confirmation = required.ge(threshold).sum(axis=1).ge(2)
    score = (
        0.35 * _scale(change)
        + 0.25 * _scale(acceleration)
        + 0.20 * crossing.astype(float)
        + 0.10 * persistent.astype(float)
        + 0.10 * confirmation.astype(float)
    ).rename("actionable_transition")
    return ActionableTransitionSignal(score=score.fillna(0.0))


def decompose_joint_structural(channels: pd.DataFrame) -> pd.DataFrame:
    vulnerability = structural_vulnerability_signal(channels).score
    transition = actionable_transition_signal(channels).score
    return pd.concat([vulnerability, transition], axis=1)


def count_actionable_alerts(
    warning: pd.Series,
    target_event: pd.Series,
    max_warning_days: int = 120,
) -> dict[str, float]:
    warn = pd.Series(warning).astype(bool)
    event = pd.Series(target_event).astype(bool).reindex(warn.index).fillna(False)
    groups = (warn != warn.shift(fill_value=False)).cumsum()
    hits = 0
    total = 0
    ignored_long = 0
    for _, block in warn.groupby(groups):
        if not bool(block.iloc[0]):
            continue
        total += 1
        duration = len(block)
        if duration > max_warning_days:
            ignored_long += 1
            continue
        if event.loc[block.index].any():
            hits += 1
    return {
        "actionable_alerts": float(total - ignored_long),
        "successful_actionable_alerts": float(hits),
        "ignored_long_warnings": float(ignored_long),
    }


def _channel_frame(channels: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=channels.index)
    out["M"] = pd.to_numeric(channels.get("M", 0.0), errors="coerce").clip(lower=0.0)
    out["D_contraction"] = pd.to_numeric(-channels.get("D", 0.0), errors="coerce").clip(lower=0.0)
    out["K"] = pd.to_numeric(channels.get("K", 0.0), errors="coerce").clip(lower=0.0)
    out["X"] = pd.to_numeric(channels.get("X", 0.0), errors="coerce").clip(lower=0.0)
    return out.fillna(0.0)


def _scale(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").fillna(0.0)
    high = numeric.expanding(min_periods=2).quantile(0.95).shift(1).replace(0.0, np.nan)
    return (numeric / high).clip(0.0, 1.0).fillna(0.0)
