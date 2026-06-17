"""Tests for HMM regime detector degeneracy protection.

Validates:
1. Long-form → wide panel pivot correctness
2. Per-series feature engineering produces expected columns
3. Degeneracy guards fire correctly for each condition
4. Full detect_regime output includes required metadata fields
5. Train window truncation works
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
WB_SRC = ROOT / "Workbench" / "src"
if str(WB_SRC) not in sys.path:
    sys.path.insert(0, str(WB_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.regime_detector import (
    _check_degeneracy,
    _engineer_features,
    _pivot_panel,
    _reduce_to_hmm_input,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_long_panel(n_days: int = 200, n_series: int = 5) -> pd.DataFrame:
    """Build a synthetic long-form panel with date/series_id/value."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    rows = []
    for sid_idx in range(n_series):
        sid = f"TEST:SERIES_{sid_idx}"
        base = 100 + sid_idx * 10
        values = base + np.cumsum(rng.normal(0, 1, n_days))
        for d, v in zip(dates, values):
            rows.append({"date": d, "series_id": sid, "value": v})
    return pd.DataFrame(rows)


def _make_wide_panel(n_days: int = 200, n_series: int = 5) -> pd.DataFrame:
    """Build a synthetic wide panel (date as index, columns=series)."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    data = {}
    for i in range(n_series):
        base = 100 + i * 10
        data[f"SERIES_{i}"] = base + np.cumsum(rng.normal(0, 1, n_days))
    return pd.DataFrame(data, index=dates)


# ── Test: pivot ──────────────────────────────────────────────────────────

def test_pivot_long_to_wide():
    """Long-form panel should pivot to date × series_id."""
    long_df = _make_long_panel(n_days=100, n_series=3)
    wide = _pivot_panel(long_df)

    assert isinstance(wide, pd.DataFrame)
    assert wide.shape[0] == 100  # 100 days
    assert wide.shape[1] == 3   # 3 series
    assert "TEST:SERIES_0" in wide.columns
    assert "TEST:SERIES_2" in wide.columns


def test_pivot_already_wide():
    """If panel is already wide (no series_id), return as-is."""
    wide_df = _make_wide_panel(n_days=100, n_series=3)
    result = _pivot_panel(wide_df)

    assert result.shape == wide_df.shape
    assert list(result.columns) == list(wide_df.columns)


def test_pivot_deduplicates():
    """Duplicate (date, series_id) pairs should be deduplicated (keep last)."""
    long_df = _make_long_panel(n_days=50, n_series=2)
    # Add a duplicate row with different value
    dup = long_df.iloc[0].copy()
    dup["value"] = 9999.0
    long_df = pd.concat([long_df, pd.DataFrame([dup])], ignore_index=True)

    wide = _pivot_panel(long_df)
    # Should not raise, should have 50 rows
    assert wide.shape[0] == 50


# ── Test: feature engineering ────────────────────────────────────────────

def test_engineer_features_produces_expected_columns():
    """Each series should produce 6 feature columns."""
    wide = _make_wide_panel(n_days=200, n_series=3)
    features = _engineer_features(wide)

    # 3 series × 6 features = 18 (minus any dropped for zero variance)
    assert features.shape[1] >= 12  # at least 4 per series after drops
    assert features.shape[0] > 100  # most rows survive

    # Check naming convention
    for col in features.columns:
        assert any(
            col.endswith(suffix)
            for suffix in ["_ret_5", "_ret_20", "_vol_20", "_zscore_60", "_drawdown", "_trend_20"]
        ), f"Unexpected column name: {col}"


def test_engineer_features_no_all_nan():
    """Features should not have all-NaN columns after engineering."""
    wide = _make_wide_panel(n_days=200, n_series=3)
    features = _engineer_features(wide)

    for col in features.columns:
        assert features[col].notna().any(), f"Column {col} is all NaN"


def test_engineer_features_drops_short_series():
    """Series with too many NaN should be dropped."""
    wide = _make_wide_panel(n_days=200, n_series=3)
    # Inject NaN into one series (first 180 of 200 rows)
    wide.iloc[:180, 0] = np.nan
    features = _engineer_features(wide)

    # SERIES_0 should be dropped (only 20 valid values)
    assert "SERIES_0_ret_5" not in features.columns


# ── Test: degeneracy guards ─────────────────────────────────────────────

def test_degeneracy_single_feature():
    """feature_count < 3 should flag 'single_feature' and mark unusable."""
    result = _check_degeneracy(
        feature_count=1,
        state_probs={"compression": 0.33, "volatile": 0.33, "crisis": 0.34},
        state_seq=np.array([0, 1, 2, 0, 1]),
        sample_days=500,
    )
    assert not result["usable_for_core_judgment"]
    assert "single_feature" in result["flags"]
    assert any("single_feature" in w for w in result["warnings"])


def test_degeneracy_overconfident():
    """State probability > 0.99 should flag 'overconfident'."""
    result = _check_degeneracy(
        feature_count=5,
        state_probs={"compression": 0.005, "volatile": 0.005, "crisis": 0.99},
        state_seq=np.array([2, 2, 2, 2, 2]),
        sample_days=500,
    )
    assert not result["usable_for_core_judgment"]
    assert "overconfident" in result["flags"]


def test_degeneracy_state_collapse():
    """One state occupying >90% of sequence should flag 'state_collapse'."""
    state_seq = np.array([0] * 95 + [1] * 3 + [2] * 2)  # 95% state 0
    result = _check_degeneracy(
        feature_count=5,
        state_probs={"compression": 0.95, "volatile": 0.03, "crisis": 0.02},
        state_seq=state_seq,
        sample_days=500,
    )
    assert not result["usable_for_core_judgment"]
    assert "state_collapse" in result["flags"]


def test_degeneracy_insufficient_data():
    """sample_days < 252 should flag 'insufficient_data'."""
    result = _check_degeneracy(
        feature_count=5,
        state_probs={"compression": 0.33, "volatile": 0.33, "crisis": 0.34},
        state_seq=np.array([0, 1, 2]),
        sample_days=100,
    )
    assert not result["usable_for_core_judgment"]
    assert "insufficient_data" in result["flags"]


def test_degeneracy_all_clean():
    """When all checks pass, usable_for_core_judgment should be True."""
    state_seq = np.array([0] * 30 + [1] * 40 + [2] * 30)
    result = _check_degeneracy(
        feature_count=10,
        state_probs={"compression": 0.30, "volatile": 0.40, "crisis": 0.30},
        state_seq=state_seq,
        sample_days=500,
    )
    assert result["usable_for_core_judgment"]
    assert len(result["flags"]) == 0


def test_degeneracy_multiple_flags():
    """Multiple degeneracy conditions should all be flagged simultaneously."""
    state_seq = np.array([2] * 95 + [0] * 5)  # collapse + overconfident
    result = _check_degeneracy(
        feature_count=1,  # single feature
        state_probs={"compression": 0.005, "volatile": 0.005, "crisis": 0.99},
        state_seq=state_seq,
        sample_days=100,  # insufficient
    )
    assert not result["usable_for_core_judgment"]
    assert "single_feature" in result["flags"]
    assert "overconfident" in result["flags"]
    assert "state_collapse" in result["flags"]
    assert "insufficient_data" in result["flags"]
    assert len(result["warnings"]) >= 4


# ── Test: PCA reduction ─────────────────────────────────────────────────

def test_reduce_to_hmm_input_low_dim():
    """If features ≤ max_dims, return as-is."""
    data = pd.DataFrame(
        np.random.randn(100, 2),
        columns=["a", "b"],
    )
    obs, names = _reduce_to_hmm_input(data, max_dims=3)
    assert obs.shape == (100, 2)
    assert names == ["a", "b"]


def test_reduce_to_hmm_input_high_dim():
    """If features > max_dims, reduce via PCA."""
    data = pd.DataFrame(
        np.random.randn(100, 10),
        columns=[f"f{i}" for i in range(10)],
    )
    obs, names = _reduce_to_hmm_input(data, max_dims=3)
    assert obs.shape == (100, 3)
    assert len(names) == 3
    assert names[0] == "pca_0"


# ── Integration: detect_regime with synthetic data ──────────────────────

def test_detect_regime_output_structure(tmp_path):
    """Full detect_regime should produce all required fields."""
    from ml.regime_detector import detect_regime

    # Build a synthetic parquet panel
    panel = _make_long_panel(n_days=300, n_series=4)
    panel_path = tmp_path / "test_panel.parquet"
    panel.to_parquet(panel_path)

    result = detect_regime(
        panel_path,
        source_release="test",
        source_created_at="2026-06-17",
        write=False,
        train_window=200,
    )

    # Check top-level structure
    assert result["schema_version"] == "workbench.ml_signal.v1"
    assert result["signal_type"] == "regime"
    assert result["source_release"] == "test"

    # Check regime section
    regime = result["regime"]
    assert regime["current"] in ("compression", "volatile", "crisis")
    assert 0 <= regime["probability"] <= 1
    assert set(regime["state_probs"].keys()) == {"compression", "volatile", "crisis"}
    assert abs(sum(regime["state_probs"].values()) - 1.0) < 0.01

    # Check stability section
    stability = result["stability"]
    assert stability["feature_count"] > 0
    assert stability["sample_days"] <= 200  # windowed
    assert stability["train_window"] == 200
    assert "train_window_note" in stability
    assert "posterior_entropy" in stability

    # Check degeneracy section
    degeneracy = result["degeneracy"]
    assert "usable_for_core_judgment" in degeneracy
    assert "warnings" in degeneracy
    assert "flags" in degeneracy
    assert isinstance(degeneracy["warnings"], list)
    assert isinstance(degeneracy["flags"], list)

    # Check provenance
    provenance = result["provenance"]
    assert "input_row_count_raw" in provenance
    assert "input_row_count_wide" in provenance
    assert "input_date_range" in provenance
    assert "feature_columns" in provenance
    assert "hmm_input_dimensions" in provenance


def test_detect_regime_train_window_truncation(tmp_path):
    """Train window should truncate data to most recent N rows."""
    from ml.regime_detector import detect_regime

    panel = _make_long_panel(n_days=500, n_series=3)
    panel_path = tmp_path / "test_panel.parquet"
    panel.to_parquet(panel_path)

    result = detect_regime(
        panel_path,
        source_release="test",
        source_created_at="2026-06-17",
        write=False,
        train_window=100,
    )

    assert result["stability"]["sample_days"] <= 100
    assert "last 100" in result["stability"]["train_window_note"]


def test_detect_regime_current_100pct_crisis_is_flagged(tmp_path):
    """If the model produces 100% crisis, it should be flagged as degenerate."""
    from ml.regime_detector import detect_regime

    # Create a panel that will likely produce degenerate output
    # Use only 1 series with very few data points
    rng = np.random.default_rng(99)
    dates = pd.bdate_range("2020-01-01", periods=80)
    panel = pd.DataFrame({
        "date": list(dates) * 1,
        "series_id": ["TEST:SINGLE"] * 80,
        "value": 100 + np.cumsum(rng.normal(0, 10, 80)),
    })
    panel_path = tmp_path / "sparse_panel.parquet"
    panel.to_parquet(panel_path)

    result = detect_regime(
        panel_path,
        source_release="test",
        source_created_at="2026-06-17",
        write=False,
        train_window=200,
    )

    # With 1 series, feature_count should be low → single_feature warning
    assert "single_feature" in result["degeneracy"]["flags"] or \
           result["degeneracy"]["usable_for_core_judgment"] is False


def test_check_degeneracy_empty_sequence():
    """Empty state sequence should not crash."""
    result = _check_degeneracy(
        feature_count=5,
        state_probs={"compression": 0.33, "volatile": 0.33, "crisis": 0.34},
        state_seq=np.array([], dtype=int),
        sample_days=500,
    )
    # Should not crash — empty sequence means no state_collapse check
    assert result["usable_for_core_judgment"] is True


def test_check_degeneracy_zero_features():
    """Zero features should flag 'no_features'."""
    result = _check_degeneracy(
        feature_count=0,
        state_probs={"compression": 0.33, "volatile": 0.33, "crisis": 0.34},
        state_seq=np.array([0, 1, 2]),
        sample_days=500,
    )
    assert not result["usable_for_core_judgment"]
    assert "no_features" in result["flags"]
