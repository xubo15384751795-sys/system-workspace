from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.professional_methods import (
    bocpd_change_probability,
    build_forward_stress_events,
    causal_pit,
    causal_robust_zscore,
    chronological_isotonic_calibration,
    ciss_index,
    continuous_position,
    deflated_sharpe_ratio,
    incremental_logistic_test,
    kalman_local_level,
    positive_cusum,
)


def test_robust_z_and_pit_are_strictly_causal() -> None:
    base = pd.Series(np.arange(300, dtype=float))
    changed = base.copy()
    changed.iloc[250:] = 1_000_000.0
    z_base = causal_robust_zscore(base, window=100, min_periods=50)
    z_changed = causal_robust_zscore(changed, window=100, min_periods=50)
    pit_base = causal_pit(base, window=100, min_periods=50)
    pit_changed = causal_pit(changed, window=100, min_periods=50)
    pd.testing.assert_series_equal(z_base.iloc[:250], z_changed.iloc[:250])
    pd.testing.assert_series_equal(pit_base.iloc[:250], pit_changed.iloc[:250])


def test_pit_midrank_for_constant_history() -> None:
    values = pd.Series([1.0] * 20)
    pit = causal_pit(values, window=None, min_periods=5)
    assert pit.iloc[-1] == 0.5


def test_kalman_anchor_tracks_level_shift_without_lookahead() -> None:
    values = pd.Series(np.r_[np.zeros(100), np.ones(100) * 10.0])
    result = kalman_local_level(values, process_variance=0.1, observation_variance=1.0)
    assert result.anchor.iloc[99] < 1.0
    assert result.innovation_z.iloc[100] > 5.0
    assert result.anchor.iloc[-1] > 9.0


def test_cusum_accumulates_persistent_small_deterioration() -> None:
    score = pd.Series([0.0] * 20 + [0.5] * 30)
    result = positive_cusum(score, reference=0.25, threshold=5.0)
    assert not result["alarm"].iloc[25]
    assert result["alarm"].iloc[-1]
    assert result["stress_probability"].between(0.0, 1.0).all()


def test_bocpd_spikes_when_level_jumps() -> None:
    score = pd.Series([0.0] * 80 + [4.0] * 40)
    probability = bocpd_change_probability(
        score, hazard=1.0 / 80.0, observation_variance=0.25, recent_run_days=5
    )
    pre = float(probability.iloc[60:80].mean())
    post = float(probability.iloc[80:86].mean())
    assert post > pre + 0.05
    assert probability.dropna().between(0.0, 1.0).all()


def test_ciss_rewards_correlated_joint_stress_and_handles_missing() -> None:
    index = pd.RangeIndex(100)
    common = pd.Series(np.linspace(0.1, 0.9, 100), index=index)
    joint = pd.DataFrame({"M": common, "D": common, "K": common, "X": common})
    independent = pd.DataFrame({
        "M": common,
        "D": common.iloc[::-1].reset_index(drop=True),
        "K": np.tile([0.2, 0.8], 50),
        "X": np.tile([0.8, 0.2], 50),
    }, index=index)
    joint_score = ciss_index(joint, span=20, min_periods=10)["ciss_sqrt"]
    independent_score = ciss_index(independent, span=20, min_periods=10)["ciss_sqrt"]
    assert joint_score.iloc[-1] > independent_score.iloc[-1]
    joint.loc[90:, "X"] = np.nan
    missing = ciss_index(joint, span=20, min_periods=10)
    assert missing["ciss_sqrt"].iloc[-1] > 0
    assert missing["coverage"].iloc[-1] == 0.75


def test_forward_event_threshold_uses_only_matured_history() -> None:
    index = pd.date_range("2000-01-01", periods=800, freq="B")
    price = pd.Series(100 * np.exp(np.cumsum(np.sin(np.arange(800)) * 0.001)), index=index)
    changed = price.copy()
    changed.iloc[700:] *= np.linspace(1.0, 0.2, 100)
    original = build_forward_stress_events(price, min_history=100, threshold_window=500)
    revised = build_forward_stress_events(changed, min_history=100, threshold_window=500)
    pd.testing.assert_series_equal(
        original["causal_vol_threshold"].iloc[:700],
        revised["causal_vol_threshold"].iloc[:700],
    )


def test_forward_event_and_logic_is_stricter_than_or() -> None:
    index = pd.date_range("2000-01-01", periods=800, freq="B")
    rng = np.random.default_rng(0)
    price = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 800))), index=index)
    or_events = build_forward_stress_events(price, logic="or", min_history=100, threshold_window=500)
    and_events = build_forward_stress_events(price, logic="and", min_history=100, threshold_window=500)
    or_rate = float(or_events["stress_event"].dropna().astype(bool).mean())
    and_rate = float(and_events["stress_event"].dropna().astype(bool).mean())
    assert and_rate <= or_rate


def test_sticky_hmm_and_jump_regime_emit_probabilities() -> None:
    pytest.importorskip("hmmlearn")
    from scripts.professional_methods import (
        jump_cluster_regime_probability,
        sticky_gaussian_hmm_probability,
    )

    score = pd.Series(np.r_[np.zeros(300), np.ones(200) * 3.0, np.zeros(100)])
    hmm = sticky_gaussian_hmm_probability(score, refit_every=80, min_fit=120, max_fit_window=400)
    jump = jump_cluster_regime_probability(score, min_fit=80, refit_every=40)
    assert hmm.dropna().between(0.0, 1.0).all()
    assert jump.dropna().between(0.0, 1.0).all()
    assert hmm.notna().sum() > 50
    assert jump.notna().sum() > 50
    assert jump.max() > jump.min()


def test_rolling_first_factor_anchors_stress_positive() -> None:
    from scripts.professional_methods import rolling_first_factor

    index = pd.RangeIndex(200)
    frame = pd.DataFrame(
        {
            "M": np.linspace(0, 1, 200),
            "D": np.linspace(0, 1, 200) + 0.05,
            "K": np.linspace(0, 1, 200) - 0.02,
            "X": np.linspace(0, 1, 200),
        },
        index=index,
    )
    factor = rolling_first_factor(frame, window=80, min_periods=40, step=5)
    assert factor.dropna().iloc[-1] > 0


def test_continuous_position_respects_quality_cap() -> None:
    index = pd.date_range("2020-01-01", periods=100, freq="B")
    stress = pd.Series(0.25, index=index)
    returns = pd.Series(0.001, index=index)
    result = continuous_position(stress, returns, quality_cap=0.5)
    assert result["position"].dropna().max() <= 0.5


def test_deflated_sharpe_penalizes_more_trials() -> None:
    one = deflated_sharpe_ratio(1.0, 1000, 1)
    many = deflated_sharpe_ratio(1.0, 1000, 100)
    assert many["deflated_sharpe_probability"] < one["deflated_sharpe_probability"]


def test_deflated_sharpe_expected_max_is_on_annualized_sharpe_scale() -> None:
    result = deflated_sharpe_ratio(0.5, 2520, 50)
    assert 0.0 < result["expected_max_sharpe"] < 1.0


def test_folded_pit_is_two_sided_and_causal() -> None:
    from scripts.professional_methods import folded_pit

    rng = np.random.default_rng(0)
    base = pd.Series(rng.normal(0.0, 1.0, 400))
    changed = base.copy()
    changed.iloc[350] = 20.0
    changed.iloc[351] = -20.0
    fold_base = folded_pit(base, window=200, min_periods=50)
    fold_changed = folded_pit(changed, window=200, min_periods=50)
    pd.testing.assert_series_equal(fold_base.iloc[:350], fold_changed.iloc[:350])
    assert fold_base.dropna().between(0.0, 1.0).all()
    calm = float(fold_changed.iloc[200:340].mean())
    assert fold_changed.iloc[350] > calm + 0.2
    assert fold_changed.iloc[351] > calm + 0.2
    assert fold_changed.iloc[350] > 0.8
    assert fold_changed.iloc[351] > 0.8


def test_release_intensity_features_freeze_train_crit_and_build_f1() -> None:
    from scripts.professional_methods import release_intensity_features

    index = pd.date_range("2010-01-01", periods=3000, freq="B")
    rng = np.random.default_rng(7)
    channels = pd.DataFrame(
        {
            "channel_M": rng.normal(0, 1, len(index)).cumsum(),
            "channel_D_contraction": rng.normal(0, 1, len(index)).cumsum(),
            "channel_K": rng.normal(0, 1, len(index)).cumsum(),
            "channel_X_agg": rng.normal(0, 1, len(index)).cumsum(),
        },
        index=index,
    )
    # Spike D and K after train end so f1 lights up.
    channels.loc["2019-06-01":, "channel_D_contraction"] += 8.0
    channels.loc["2019-06-01":, "channel_K"] += 8.0
    feats = release_intensity_features(channels, train_end="2018-12-31", min_periods=126)
    assert feats["d_crit_train"].nunique(dropna=True) == 1
    assert feats["k_crit_train"].nunique(dropna=True) == 1
    assert feats.loc["2019-07-01":, "f1_release_kernel"].max() > 0
    assert feats["f2_forced_sale"].notna().any()
    assert feats["f3_injection_amp"].notna().any()


def test_isotonic_calibration_only_emits_after_embargoed_split() -> None:
    target = pd.Series(([False] * 4 + [True]) * 100)
    raw = pd.Series(np.linspace(0.0, 1.0, len(target)))
    calibrated = chronological_isotonic_calibration(target, raw, train_fraction=0.6, embargo=20)
    assert calibrated.iloc[:320].isna().all()
    assert calibrated.dropna().between(0.0, 1.0).all()


def test_incremental_logistic_test_emits_diebold_mariano_gate() -> None:
    """The §7.5 incremental significance gate (DM p<0.05) must be surfaced.

    A candidate with genuine predictive content should produce a finite DM
    statistic; the delta.diebold_mariano block must be JSON-safe (NaN->None).
    """
    rng = np.random.default_rng(7)
    n = 800
    index = pd.date_range("2015-01-02", periods=n, freq="B")
    # Baseline: weak noise. Candidate: informative of the event.
    baseline = pd.DataFrame(
        {"vol": rng.normal(0.0, 1.0, n), "funding": rng.normal(0.0, 1.0, n)},
        index=index,
    )
    latent = rng.normal(0.0, 1.0, n)
    target = pd.Series((latent > 1.0).astype(int), index=index)
    candidate = pd.Series(latent + rng.normal(0.0, 0.3, n), index=index, name="cand")

    result = incremental_logistic_test(target, baseline, candidate, embargo=20)

    assert result["status"] == "ok"
    delta = result["delta"]
    assert "diebold_mariano" in delta
    dm = delta["diebold_mariano"]
    assert {"n", "mean_diff", "dm_stat", "p_value"} <= set(dm)
    assert isinstance(dm["n"], int)
    # An informative candidate should yield a finite, significant DM statistic.
    assert dm["mean_diff"] is not None
    assert dm["dm_stat"] is not None
    assert dm["p_value"] is not None
    assert dm["p_value"] < 0.05
