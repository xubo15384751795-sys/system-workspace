"""Tests for public-level + residual-onset paper path."""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from scripts.public_residual_stress import (
    build_public_residual_bundle,
    dual_stress_position,
    public_level_probability,
    residual_onset_probability,
    residual_velocity_vs_public,
    residual_vs_public,
)


def test_public_level_fails_closed_on_missing_components() -> None:
    """When a public component is entirely missing, P_public is NaN for every
    date under the default (full-coverage) fail-closed policy - NOT silently
    renormalized over the surviving subset.

    This is the Phase A fix for the 2026-05..07 NFCI-only degradation: a
    stale/missing OFR or CISS must not collapse P_public to a single-component
    value without any signal. Research callers (capability board) may opt out
    via min_components=1.
    """
    index = pd.date_range("2020-01-01", periods=300, freq="B")
    public = pd.DataFrame(
        {
            "ofr_fsi": np.linspace(0, 1, 300),
            "nfci": np.linspace(0.2, 0.8, 300),
            "ecb_ciss": [np.nan] * 300,  # CISS entirely missing
        },
        index=index,
    )
    # Default: fail-closed (require all 3 components) -> all NaN.
    p_closed = public_level_probability(public, min_periods=50)
    assert p_closed.notna().sum() == 0, (
        "incomplete public coverage must yield NaN P_public (fail-closed), "
        f"got {p_closed.notna().sum()} non-NaN values"
    )

    # Research opt-out: min_components=1 preserves the old renormalizing
    # behavior so capability-board NAV comparisons stay comparable.
    p_research = public_level_probability(
        public, min_periods=50, min_components=1, research_only=True
    )
    assert p_research.dropna().between(0.0, 1.0).all()
    assert p_research.notna().sum() > 100


def test_residual_onset_rises_when_channel_pulls_ahead() -> None:
    index = pd.RangeIndex(400)
    public = pd.Series(np.linspace(0.3, 0.4, 400), index=index)
    channel = public.copy()
    channel.iloc[250:] = channel.iloc[250:] + np.linspace(0, 0.5, 150)
    residual = residual_vs_public(channel, public)
    onset = residual_onset_probability(
        residual, method="velocity", residual_mode="level", velocity_window=20, min_periods=50
    )
    assert onset.dropna().between(0.0, 1.0).all()
    assert float(onset.iloc[300:350].mean()) > float(onset.iloc[100:150].mean())


def test_velocity_residual_mode_detects_relative_heating() -> None:
    index = pd.RangeIndex(400)
    public = pd.Series(0.4, index=index)
    channel = public.copy()
    # Channel accelerates while public stays flat → velocity residual rises.
    ramp = np.concatenate([np.zeros(250), np.linspace(0, 0.6, 150)])
    channel = channel + ramp
    residual = residual_velocity_vs_public(channel, public, velocity_window=20, min_periods=50)
    onset = residual_onset_probability(
        residual, method="velocity", residual_mode="velocity", min_periods=50
    )
    assert onset.dropna().between(0.0, 1.0).all()
    early = onset.iloc[160:200].mean()
    late = onset.iloc[320:360].mean()
    assert np.isfinite(early) and np.isfinite(late)
    assert float(late) > float(early)


def test_bundle_velocity_mode_and_lambda0() -> None:
    index = pd.date_range("2020-01-01", periods=260, freq="B")
    channels = pd.DataFrame(
        {name: np.linspace(0, 1, 260) for name in ("M", "D", "K", "X")},
        index=index,
    )
    public = pd.DataFrame(
        {
            "ofr_fsi": np.linspace(0, 0.5, 260),
            "nfci": np.linspace(0.1, 0.4, 260),
        },
        index=index,
    )
    returns = pd.Series(0.001, index=index)
    with_onset = build_public_residual_bundle(
        channels, public, returns, residual_mode="velocity", onset_lambda=1.0, min_periods=50
    )
    lambda0 = build_public_residual_bundle(
        channels, public, returns, residual_mode="velocity", onset_lambda=0.0, min_periods=50
    )
    assert with_onset["residual_mode"] == "velocity"
    assert with_onset["p_onset"].dropna().between(0.0, 1.0).all()
    # λ=0 ignores onset → positions weakly ≥ λ=1 when onset > 0
    assert float(lambda0["sizing"]["position"].mean()) >= float(with_onset["sizing"]["position"].mean()) - 1e-9


def test_dual_stress_position_formula() -> None:
    index = pd.date_range("2020-01-01", periods=80, freq="B")
    returns = pd.Series(0.001, index=index)
    p_public = pd.Series(0.2, index=index)
    p_onset = pd.Series(0.5, index=index)
    sized = dual_stress_position(
        p_public=p_public,
        p_onset=p_onset,
        returns=returns,
        quality_cap=1.0,
        target_volatility=0.10,
        onset_lambda=1.0,
        ewma_span=5,
    )
    # Constant tiny returns → vol small → vol_multiplier clips to 1 → w≈0.8*0.5=0.4
    assert sized["position"].dropna().iloc[-1] == pytest.approx(0.4, abs=0.05)


def test_reduced_coverage_requires_research_marker() -> None:
    public = pd.DataFrame({"nfci": [0.2] * 4, "ofr_fsi": [np.nan] * 4})
    with pytest.raises(ValueError, match="research_only=True"):
        public_level_probability(public, min_periods=1, min_components=1)


def test_causal_availability_masks_late_component_before_pit() -> None:
    index = pd.date_range("2026-01-01", periods=180, freq="B")
    public = pd.DataFrame(
        {
            "ofr_fsi": np.linspace(0.0, 1.0, len(index)),
            "nfci": np.linspace(0.2, 0.8, len(index)),
        },
        index=index,
    )
    available_at = pd.DataFrame(
        {
            "ofr_fsi": pd.Timestamp("2026-01-02", tz=UTC),
            "nfci": pd.Timestamp("2026-12-31", tz=UTC),
        },
        index=index,
    )
    decision_time = pd.Series(
        datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        index=index,
    )
    p_public = public_level_probability(
        public,
        min_periods=50,
        available_at=available_at,
        decision_time=decision_time,
    )
    assert p_public.isna().all()


def test_causal_availability_requires_both_inputs() -> None:
    public = pd.DataFrame({"nfci": [0.1, 0.2]})
    with pytest.raises(ValueError, match="provided together"):
        public_level_probability(public, available_at=pd.DataFrame({"nfci": ["2026-01-01"]}))


def test_missing_public_probability_emits_no_sizing_weight() -> None:
    index = pd.date_range("2026-01-01", periods=4, freq="B")
    sized = dual_stress_position(
        p_public=pd.Series([np.nan] * 4, index=index),
        p_onset=pd.Series(0.0, index=index),
        returns=pd.Series(0.001, index=index),
        ewma_span=2,
    )
    assert sized["position"].isna().all()
    assert (sized["public_coverage_status"] == "INSUFFICIENT_COVERAGE").all()
