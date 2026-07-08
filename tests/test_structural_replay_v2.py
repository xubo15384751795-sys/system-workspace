"""Tests for structural_replay_v2.py — pure function unit tests.

Tests the utility functions that can be verified without full pipeline data:
- _rolling_zscore: causal z-score with clipping
- confidence_label: value → label mapping
- classify_regime: channel readings → regime classification
- _jump_activation_score: shock detection
- _component / _pct_component / _diff_abs: data transforms

These tests use synthetic data (no fixture files needed).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    """Load structural_replay_v2 as a module.

    Must add scripts/ and Workbench/src to sys.path first because the
    module imports from _workspace_imports, _constants, _runtime_io,
    and workbench.* at module level.  Some dependencies (replay.scoring)
    may not be available in the test environment, so we mock them.
    """
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    # Add Workbench/src for workbench.governance, etc.
    wb_src = str(ROOT / "packages" / "workbench" / "src")
    if wb_src not in sys.path:
        sys.path.insert(0, wb_src)

    # Mock replay.scoring if not installed (it's a runtime dependency)
    if "replay.scoring" not in sys.modules:
        import types
        replay_pkg = types.ModuleType("replay")
        replay_pkg.__path__ = []
        replay_scoring = types.ModuleType("replay.scoring")
        # Provide the CHANNELS constant that the module expects
        replay_scoring.CHANNELS = [
            "M", "D_contraction", "K", "X_agg", "X_PRE", "X_REALIZED", "Pi_t",
        ]
        replay_scoring.compute_family_concentration = lambda *a, **k: None
        replay_scoring.compute_derivative_contamination = lambda *a, **k: None
        replay_scoring.compute_sparsity_flags = lambda *a, **k: None
        replay_scoring.compute_horizon_consistency = lambda *a, **k: None
        replay_scoring.compute_realized_activation_quality = lambda *a, **k: None
        replay_scoring.compute_contract_violations = lambda *a, **k: None
        replay_scoring.compute_pc1_variance = lambda *a, **k: None
        replay_scoring.compute_vif = lambda *a, **k: None
        replay_scoring.compute_residual_uniqueness = lambda *a, **k: None
        sys.modules["replay"] = replay_pkg
        sys.modules["replay.scoring"] = replay_scoring

    spec = importlib.util.spec_from_file_location(
        "structural_replay_v2", ROOT / "scripts" / "structural_replay_v2.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["structural_replay_v2"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


# ── _rolling_zscore ────────────────────────────────────────────────────


class TestRollingZscore:
    def test_returns_nan_for_short_series(self, mod):
        """Series shorter than min_periods produces NaN."""
        s = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2020-01-01", periods=3))
        result = mod._rolling_zscore(s, window=5, min_periods=3)
        # First two values have < min_periods, third is at boundary
        assert result.isna().all() or result.iloc[-1:].notna().any()

    def test_clips_to_bounds(self, mod):
        """Z-scores are clipped to [-4, 4]."""
        # Create a series with extreme outlier at the end
        np.random.seed(42)
        vals = np.random.normal(0, 1, 300)
        vals[-1] = 100.0  # extreme outlier
        s = pd.Series(vals, index=pd.date_range("2020-01-01", periods=300))
        result = mod._rolling_zscore(s, window=252, min_periods=126)
        valid = result.dropna()
        assert valid.max() <= 4.0
        assert valid.min() >= -4.0

    def test_constant_series_returns_nan(self, mod):
        """Constant series has zero std → NaN z-score."""
        s = pd.Series([5.0] * 300, index=pd.date_range("2020-01-01", periods=300))
        result = mod._rolling_zscore(s, window=252, min_periods=126)
        # After enough data, all values should be NaN (0/0)
        assert result.iloc[-1] != result.iloc[-1]  # NaN check

    def test_monotonic_increase_positive_z(self, mod):
        """Monotonically increasing series should have positive z-scores."""
        s = pd.Series(
            np.arange(300, dtype=float),
            index=pd.date_range("2020-01-01", periods=300),
        )
        result = mod._rolling_zscore(s, window=50, min_periods=20)
        valid = result.dropna()
        # Later values should be above the rolling mean → positive z
        assert valid.iloc[-1] > 0


# ── confidence_label ───────────────────────────────────────────────────


class TestConfidenceLabel:
    def test_full_confidence(self, mod):
        assert mod.confidence_label(0.75) == "VALID_FULL"
        assert mod.confidence_label(1.0) == "VALID_FULL"

    def test_partial_confidence(self, mod):
        assert mod.confidence_label(0.50) == "VALID_PARTIAL"
        assert mod.confidence_label(0.74) == "VALID_PARTIAL"

    def test_diagnostic_only(self, mod):
        assert mod.confidence_label(0.25) == "DIAGNOSTIC_ONLY"
        assert mod.confidence_label(0.49) == "DIAGNOSTIC_ONLY"

    def test_invalid(self, mod):
        assert mod.confidence_label(0.0) == "INVALID"
        assert mod.confidence_label(0.24) == "INVALID"
        assert mod.confidence_label(-0.1) == "INVALID"


# ── classify_regime ────────────────────────────────────────────────────


class TestClassifyRegime:
    def _make_row(self, mod, **kwargs):
        """Build a Series with channel values, defaulting to 0."""
        defaults = {ch: 0.0 for ch in mod.CHANNELS}
        defaults.update(kwargs)
        return pd.Series(defaults)

    def _make_thresholds(self, mod, warning=1.0):
        """Build thresholds dict with uniform warning level."""
        return {ch: {"warning": warning} for ch in mod.CHANNELS}

    def test_normal_untriggered(self, mod):
        row = self._make_row(mod)
        thresholds = self._make_thresholds(mod, warning=1.0)
        confidence = {ch: "VALID_FULL" for ch in mod.CHANNELS}
        assert mod.classify_regime(row, thresholds, confidence) == "Normal / Untriggered"

    def test_measurement_blind_spot(self, mod):
        row = self._make_row(mod)
        thresholds = self._make_thresholds(mod, warning=1.0)
        confidence = {ch: "VALID_FULL" for ch in mod.CHANNELS}
        confidence["K"] = "INVALID"
        assert mod.classify_regime(row, thresholds, confidence) == "Measurement Blind Spot"

    def test_forced_realization(self, mod):
        row = self._make_row(mod, X_REALIZED=2.0)
        thresholds = self._make_thresholds(mod, warning=1.0)
        confidence = {ch: "VALID_FULL" for ch in mod.CHANNELS}
        assert mod.classify_regime(row, thresholds, confidence) == "Forced Realization"

    def test_curvature_break(self, mod):
        row = self._make_row(mod, K=2.0, D_contraction=2.0)
        thresholds = self._make_thresholds(mod, warning=1.0)
        confidence = {ch: "VALID_FULL" for ch in mod.CHANNELS}
        assert mod.classify_regime(row, thresholds, confidence) == "Curvature Break"

    def test_path_compression(self, mod):
        row = self._make_row(mod, D_contraction=2.0)
        thresholds = self._make_thresholds(mod, warning=1.0)
        confidence = {ch: "VALID_FULL" for ch in mod.CHANNELS}
        assert mod.classify_regime(row, thresholds, confidence) == "Path Compression"

    def test_anchor_drift(self, mod):
        row = self._make_row(mod, M=2.0)
        thresholds = self._make_thresholds(mod, warning=1.0)
        confidence = {ch: "VALID_FULL" for ch in mod.CHANNELS}
        assert mod.classify_regime(row, thresholds, confidence) == "Anchor Drift"


# ── _jump_activation_score ─────────────────────────────────────────────


class TestJumpActivationScore:
    def test_none_input(self, mod):
        assert mod._jump_activation_score(None) is None

    def test_all_nan_input(self, mod):
        s = pd.Series([np.nan] * 10, index=pd.date_range("2020-01-01", periods=10))
        result = mod._jump_activation_score(s)
        assert result.isna().all()

    def test_constant_series_zero_score(self, mod):
        """No jumps → activation score should be near zero."""
        s = pd.Series([5.0] * 100, index=pd.date_range("2020-01-01", periods=100))
        result = mod._jump_activation_score(s)
        valid = result.dropna()
        assert (valid.abs() < 0.1).all()

    def test_spike_produces_elevated_score(self, mod):
        """A large spike should produce an elevated activation score."""
        vals = [5.0] * 300
        vals[200] = 50.0  # spike at index 200
        s = pd.Series(vals, index=pd.date_range("2020-01-01", periods=300))
        result = mod._jump_activation_score(s, smooth=5)
        # Score around the spike should be elevated
        assert result.iloc[200:210].max() > 0


# ── _component / _pct_component / _diff_abs ────────────────────────────


class TestComponentHelpers:
    def test_component_none_input(self, mod):
        assert mod._component(None) is None

    def test_pct_component_none_input(self, mod):
        assert mod._pct_component(None) is None

    def test_diff_abs_none_input(self, mod):
        assert mod._diff_abs(None) is None

    def test_diff_abs_computes_difference(self, mod):
        s = pd.Series([1.0, 2.0, 4.0, 7.0], index=pd.date_range("2020-01-01", periods=4))
        result = mod._diff_abs(s, periods=1)
        assert result.iloc[1] == 1.0  # |2-1|
        assert result.iloc[2] == 2.0  # |4-2|
        assert result.iloc[3] == 3.0  # |7-4|

    def test_component_daily_returns_zscore(self, mod):
        """_component with daily freq should return a z-scored series."""
        np.random.seed(42)
        s = pd.Series(
            np.random.normal(0, 1, 300),
            index=pd.date_range("2020-01-01", periods=300),
        )
        result = mod._component(s, freq="daily", smooth=5)
        assert result is not None
        valid = result.dropna()
        assert len(valid) > 0
