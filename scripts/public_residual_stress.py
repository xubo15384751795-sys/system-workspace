"""Public-index level stress + residual onset — paper-path only.

Design (capability pivot):
  - Level stress comes from free public indices (OFR / NFCI / CISS), not ours.
  - Our only incremental job is residual onset. Two residual modes (A/B):
      A level:    velocity/CUSUM on (channel_PIT − public_PIT)
      B velocity: onset on (channel_velocity_PIT − public_velocity_PIT)
  - Decision weight (shadow/paper):
        w = w_max · vol_target · (1 − P_public) · (1 − λ · P_onset)
  - Never wired to live execution from this module.
"""
from __future__ import annotations

import logging
import sys
from math import sqrt
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from professional_methods import (  # noqa: E402
    TRADING_DAYS,
    build_forward_stress_events,
    causal_pit,
    causal_robust_zscore,
    incremental_logistic_test,
    positive_cusum,
    probability_metrics,
)

ResidualMode = Literal["level", "velocity"]

PUBLIC_SERIES_ALIASES: dict[str, tuple[str, ...]] = {
    "ofr_fsi": ("OFR_FSI", "FRED:OFR_FSI"),
    "nfci": ("FRED:NFCI", "NFCI"),
    "ecb_ciss": ("CISS", "ECB:CISS", "FRED:CISS"),
}


def extract_public_levels(panel: pd.DataFrame) -> pd.DataFrame:
    """Pull OFR / NFCI / CISS columns from a wide benchmark panel."""
    out: dict[str, pd.Series] = {}
    for label, names in PUBLIC_SERIES_ALIASES.items():
        for name in names:
            if name in panel.columns:
                out[label] = pd.to_numeric(panel[name], errors="coerce")
                break
    return pd.DataFrame(out, index=panel.index)


def public_level_probability(
    public_levels: pd.DataFrame,
    *,
    min_periods: int = 126,
    min_components: int | None = None,
) -> pd.Series:
    """Equal-weight mean of causal PITs across available public stress indices.

    Fail-closed on incomplete coverage: when fewer than ``min_components``
    public components are available on a date, P_public is NaN for that date
    rather than silently renormalized over the surviving subset. Default
    ``min_components=None`` means "require all components" (full coverage) -
    this is the paper-portfolio / decision-adjacent path. Research callers
    (capability board comparison) may pass ``min_components=1`` to preserve
    the old renormalizing behavior for historical NAV comparison.

    The renormalization failure mode - OFR+CISS NaN -> NFCI-only P_public,
    silently driving a ~0.14 bias and ~15% sizing error for ~9 weeks - is
    documented in routing decision 2026-07-12-g1-contrast-and-freshness-fix
    and governance/open_threads.yaml id shadow-nav-degradation-annotation.
    Paper_portfolio's run_paper_portfolio translates a NaN P_public into a
    HOLD-existing position (see _compute_target_series hold branch).
    """
    if public_levels.empty:
        return pd.Series(np.nan, index=public_levels.index, name="p_public")
    pits = pd.DataFrame(
        {
            column: causal_pit(public_levels[column], min_periods=min_periods)
            for column in public_levels.columns
        },
        index=public_levels.index,
    )
    full_components = pits.shape[1]
    # Default: require the full component set (fail-closed). A caller may
    # lower this (e.g. capability_board research comparison passes 1).
    required_components = min_components if min_components is not None else full_components
    available = pits.notna().sum(axis=1)
    degraded = available[available < required_components]
    if not degraded.empty:
        logging.warning(
            "p_public component coverage below required (%d) on %d of %d dates "
            "(min=%d component(s)); those dates return NaN (fail-closed) instead of "
            "renormalizing. Components: %s",
            required_components,
            len(degraded),
            len(pits),
            int(degraded.min()),
            list(pits.columns),
        )
    p_public = pits.mean(axis=1, skipna=True).rename("p_public")
    # Fail-closed: NaN where coverage is incomplete.
    p_public = p_public.where(available >= required_components)
    return p_public


def channel_level_probability(
    channels: pd.DataFrame,
    *,
    min_periods: int = 126,
) -> pd.Series:
    """Equal-weight PIT of channel levels (M/D/K/X)."""
    pits = pd.DataFrame(
        {column: causal_pit(channels[column], min_periods=min_periods) for column in channels.columns},
        index=channels.index,
    )
    return pits.mean(axis=1, skipna=True).rename("p_channel_level")


def residual_vs_public(
    channel_level: pd.Series,
    public_level: pd.Series,
) -> pd.Series:
    """Channel PIT minus public PIT — positive = our channels hotter than public."""
    aligned = pd.concat(
        [channel_level.rename("channel"), public_level.rename("public")],
        axis=1,
    )
    return (aligned["channel"] - aligned["public"]).rename("residual_vs_public")


def velocity_pit(
    level: pd.Series,
    *,
    velocity_window: int = 20,
    min_periods: int = 126,
) -> pd.Series:
    """Causal PIT of level changes — public/channel heating rate on [0, 1]."""
    return causal_pit(level.diff(velocity_window), min_periods=min_periods)


def residual_velocity_vs_public(
    channel_level: pd.Series,
    public_level: pd.Series,
    *,
    velocity_window: int = 20,
    min_periods: int = 126,
) -> pd.Series:
    """Variant B: channel_velocity_PIT − public_velocity_PIT."""
    channel_v = velocity_pit(
        channel_level, velocity_window=velocity_window, min_periods=min_periods
    )
    public_v = velocity_pit(
        public_level, velocity_window=velocity_window, min_periods=min_periods
    )
    return residual_vs_public(channel_v, public_v).rename("residual_velocity_vs_public")


def residual_onset_probability(
    residual: pd.Series,
    *,
    method: str = "velocity",
    residual_mode: ResidualMode | str = "level",
    velocity_window: int = 20,
    cusum_reference: float = 0.2,
    cusum_threshold: float = 5.0,
    min_periods: int = 126,
) -> pd.Series:
    """Onset detector on residual.

    - residual_mode=level (A): velocity PIT or CUSUM of the level residual.
    - residual_mode=velocity (B): residual is already velocity-PIT space;
      map with causal PIT (or CUSUM) — do not double-diff.
    """
    method_key = method.strip().lower()
    mode_key = str(residual_mode).strip().lower()
    if method_key == "cusum":
        z = causal_robust_zscore(residual, min_periods=min_periods, clip=None)
        return positive_cusum(
            z.fillna(0.0),
            reference=cusum_reference,
            threshold=cusum_threshold,
        )["stress_probability"].rename("p_onset")
    if mode_key == "velocity":
        # Already a velocity residual; PIT maps positive relative heating to onset.
        return causal_pit(residual, min_periods=min_periods).rename("p_onset")
    velocity = residual.diff(velocity_window)
    return causal_pit(velocity, min_periods=min_periods).rename("p_onset")


def dual_stress_position(
    *,
    p_public: pd.Series,
    p_onset: pd.Series,
    returns: pd.Series,
    quality_cap: pd.Series | float = 1.0,
    target_volatility: float = 0.10,
    onset_lambda: float = 1.0,
    ewma_span: int = 20,
) -> pd.DataFrame:
    """w = w_max · vol_target · (1 − P_public) · (1 − λ · P_onset)."""
    ret = pd.to_numeric(returns, errors="coerce")
    index = ret.index
    pub = p_public.reindex(index).clip(0.0, 1.0)
    onset = p_onset.reindex(index).clip(0.0, 1.0)
    lam = float(np.clip(onset_lambda, 0.0, 1.0))
    volatility = ret.ewm(span=ewma_span, adjust=False, min_periods=ewma_span).std() * sqrt(TRADING_DAYS)
    vol_multiplier = (target_volatility / volatility.where(volatility > 1e-8)).clip(upper=1.0)
    # Near-zero realized vol → full vol budget (clip already caps at 1).
    vol_multiplier = vol_multiplier.fillna(1.0).where(ret.notna(), np.nan)
    if np.isscalar(quality_cap):
        quality = pd.Series(float(quality_cap), index=index)
    else:
        quality = quality_cap.reindex(index).astype(float)
    quality = quality.clip(0.0, 1.0)
    position = (
        quality
        * vol_multiplier
        * (1.0 - pub.fillna(0.5))
        * (1.0 - lam * onset.fillna(0.0))
    ).clip(0.0, 1.0)
    return pd.DataFrame(
        {
            "estimated_volatility": volatility,
            "volatility_multiplier": vol_multiplier,
            "quality_cap": quality,
            "p_public": pub,
            "p_onset": onset,
            "onset_lambda": lam,
            "position": position,
        },
        index=index,
    )


def build_public_residual_bundle(
    channels: pd.DataFrame,
    public_levels: pd.DataFrame,
    returns: pd.Series,
    *,
    onset_method: str = "velocity",
    residual_mode: ResidualMode | str = "level",
    onset_lambda: float = 1.0,
    velocity_window: int = 20,
    target_volatility: float = 0.10,
    min_periods: int = 126,
    min_components: int | None = None,
) -> dict[str, Any]:
    """One-shot construction of public level, residual onset, and paper weights.

    ``min_components`` is forwarded to ``public_level_probability``: None
    (default) = fail-closed on incomplete public-component coverage; 1 =
    preserve the old renormalizing behavior (research/capability-board only).
    """
    mode_key = str(residual_mode).strip().lower()
    if mode_key not in {"level", "velocity"}:
        raise ValueError(f"residual_mode must be 'level' or 'velocity', got {residual_mode!r}")
    p_public = public_level_probability(
        public_levels, min_periods=min_periods, min_components=min_components
    )
    p_channel = channel_level_probability(channels, min_periods=min_periods)
    if mode_key == "velocity":
        residual = residual_velocity_vs_public(
            p_channel,
            p_public,
            velocity_window=velocity_window,
            min_periods=min_periods,
        )
    else:
        residual = residual_vs_public(p_channel, p_public)
    p_onset = residual_onset_probability(
        residual,
        method=onset_method,
        residual_mode=mode_key,  # type: ignore[arg-type]
        velocity_window=velocity_window,
        min_periods=min_periods,
    )
    quality = channels.notna().mean(axis=1)
    sized = dual_stress_position(
        p_public=p_public,
        p_onset=p_onset,
        returns=returns,
        quality_cap=quality,
        target_volatility=target_volatility,
        onset_lambda=onset_lambda,
    )
    return {
        "p_public": p_public,
        "p_channel_level": p_channel,
        "residual_mode": mode_key,
        "residual": residual,
        "p_onset": p_onset,
        "sizing": sized,
    }


def residual_incremental_vs_public(
    target: pd.Series,
    p_public: pd.Series,
    p_onset: pd.Series,
    *,
    embargo: int = 20,
) -> dict[str, Any]:
    """β₂ / ΔAUC of onset on top of public level (the weekly board table)."""
    baseline = pd.DataFrame({"p_public": p_public})
    return incremental_logistic_test(target, baseline, p_onset, embargo=embargo)


def event_definition_sensitivity(
    price: pd.Series,
    probability: pd.Series,
    *,
    defs: tuple[dict[str, Any], ...] | None = None,
) -> list[dict[str, Any]]:
    """AUC under several event definitions — check sign/ranking consistency."""
    specs = defs or (
        {"name": "rv10_or_dd5", "vol_quantile": 0.90, "drawdown_threshold": -0.05, "logic": "or"},
        {"name": "rv5_or_dd5", "vol_quantile": 0.95, "drawdown_threshold": -0.05, "logic": "or"},
        {"name": "rv10_or_dd8", "vol_quantile": 0.90, "drawdown_threshold": -0.08, "logic": "or"},
        {"name": "rv5_or_dd8", "vol_quantile": 0.95, "drawdown_threshold": -0.08, "logic": "or"},
        {"name": "and_rv10_dd5", "vol_quantile": 0.90, "drawdown_threshold": -0.05, "logic": "and"},
    )
    rows: list[dict[str, Any]] = []
    for spec in specs:
        events = build_forward_stress_events(
            price,
            vol_quantile=float(spec["vol_quantile"]),
            drawdown_threshold=float(spec["drawdown_threshold"]),
            logic=str(spec["logic"]),
        )
        metrics = probability_metrics(events["stress_event"], probability)
        rows.append(
            {
                "definition": spec["name"],
                "logic": spec["logic"],
                "vol_quantile": spec["vol_quantile"],
                "drawdown_threshold": spec["drawdown_threshold"],
                "event_rate": metrics.get("event_rate"),
                "roc_auc": metrics.get("roc_auc"),
                "pr_auc": metrics.get("pr_auc"),
                "brier": metrics.get("brier"),
                "n": metrics.get("n"),
            }
        )
    aucs = [row["roc_auc"] for row in rows if isinstance(row["roc_auc"], (int, float)) and np.isfinite(row["roc_auc"])]
    rows.append(
        {
            "definition": "_consistency",
            "all_above_random": bool(aucs) and all(value > 0.5 for value in aucs),
            "auc_range": (max(aucs) - min(aucs)) if len(aucs) >= 2 else None,
            "n_definitions": len(aucs),
        }
    )
    return rows
