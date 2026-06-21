"""Tests for ML validation hardening: as-of integrity and baseline comparison.

Tests:
- As-of leakage detection in judgment cards and calibration evaluations
- Baseline strategy computation (no_signal, always_warn, random_freq, simple_rule)
- Threshold review bridge candidate generation
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.asof_integrity_checker import (
    check_calibration_evaluation_order,
    check_judgment_card_forward_window,
    check_feedback_sample_timing,
)
from scripts.baseline_comparison import (
    baseline_always_warn,
    baseline_no_signal,
    baseline_random_freq,
    baseline_simple_rule,
    compute_metrics,
)
from scripts.threshold_review_bridge import build_review_candidates


# =========================================================================
# As-of integrity checker tests
# =========================================================================

class TestJudgmentCardForwardWindow:
    """Test that forward window checks detect entry_before_as_of violations."""

    def test_clean_card_has_no_issues(self):
        card = {
            "as_of": "2026-06-15",
            "outcomes": {
                "1d": {
                    "status": "evaluated",
                    "metrics": {
                        "SPY": {
                            "entry_date": "2026-06-15",
                            "exit_date": "2026-06-16",
                            "return_pct": 0.5,
                        },
                    },
                },
            },
        }
        issues = check_judgment_card_forward_window(card)
        assert len(issues) == 0

    def test_entry_before_as_of_detected(self):
        card = {
            "as_of": "2026-06-15",
            "outcomes": {
                "1d": {
                    "status": "evaluated",
                    "metrics": {
                        "SPY": {
                            "entry_date": "2026-06-14",  # before as_of
                            "exit_date": "2026-06-15",
                            "return_pct": -0.3,
                        },
                    },
                },
            },
        }
        issues = check_judgment_card_forward_window(card)
        assert any(i["type"] == "entry_before_as_of" for i in issues)
        assert any(i["severity"] == "error" for i in issues)

    def test_missing_as_of_warns(self):
        card = {"outcomes": {}}
        issues = check_judgment_card_forward_window(card)
        assert any(i["type"] == "missing_as_of" for i in issues)
        assert any(i["severity"] == "warning" for i in issues)

    def test_no_outcomes_is_clean(self):
        card = {"as_of": "2026-06-15"}
        issues = check_judgment_card_forward_window(card)
        assert len(issues) == 0


class TestCalibrationEvaluationOrder:
    """Test that evaluation order regression is detected."""

    def test_monotonic_dates_are_clean(self):
        evaluations = [
            {"as_of": "2026-06-15"},
            {"as_of": "2026-06-16"},
            {"as_of": "2026-06-17"},
        ]
        issues = check_calibration_evaluation_order(evaluations)
        assert len(issues) == 0

    def test_order_regression_detected(self):
        evaluations = [
            {"as_of": "2026-06-17"},
            {"as_of": "2026-06-15"},  # regression
        ]
        issues = check_calibration_evaluation_order(evaluations)
        assert len(issues) == 1
        assert issues[0]["type"] == "evaluation_order_regression"
        assert issues[0]["severity"] == "error"

    def test_empty_evaluations_clean(self):
        issues = check_calibration_evaluation_order([])
        assert len(issues) == 0

    def test_unparseable_dates_skipped(self):
        evaluations = [
            {"as_of": "not-a-date"},
            {"as_of": "2026-06-16"},
        ]
        issues = check_calibration_evaluation_order(evaluations)
        assert len(issues) == 0


class TestFeedbackSampleTiming:
    """Test that feedback sample timing checks work."""

    def test_clean_sample_no_issues(self):
        sample = {
            "sample_id": "test_001",
            "as_of_date": "2026-06-15",
            "forward_outcome": {
                "computed_at": "2026-06-20T12:00:00+00:00",
            },
        }
        issues = check_feedback_sample_timing(sample)
        assert len(issues) == 0

    def test_computed_before_as_of_detected(self):
        sample = {
            "sample_id": "test_002",
            "as_of_date": "2026-06-20",
            "forward_outcome": {
                "computed_at": "2026-06-15T12:00:00+00:00",  # before as_of
            },
        }
        issues = check_feedback_sample_timing(sample)
        assert any(i["type"] == "outcome_computed_before_as_of" for i in issues)

    def test_missing_forward_outcome_clean(self):
        sample = {
            "sample_id": "test_003",
            "as_of_date": "2026-06-15",
        }
        issues = check_feedback_sample_timing(sample)
        assert len(issues) == 0


# =========================================================================
# Baseline comparison tests
# =========================================================================

class TestBaselineStrategies:
    """Test that baseline strategies produce correct predictions."""

    def test_no_signal_all_false(self):
        pred = baseline_no_signal(100)
        assert len(pred) == 100
        assert pred.sum() == 0
        assert pred.dtype == bool

    def test_always_warn_all_true(self):
        pred = baseline_always_warn(100)
        assert len(pred) == 100
        assert pred.sum() == 100
        assert pred.dtype == bool

    def test_random_freq_approximate_frequency(self):
        n = 10000
        fraction = 0.3
        pred = baseline_random_freq(n, fraction, seed=42)
        assert len(pred) == n
        # With large n, should be close to target fraction
        assert abs(pred.mean() - fraction) < 0.05

    def test_random_freq_reproducible(self):
        pred1 = baseline_random_freq(1000, 0.5, seed=42)
        pred2 = baseline_random_freq(1000, 0.5, seed=42)
        np.testing.assert_array_equal(pred1, pred2)

    def test_random_freq_different_seeds_differ(self):
        pred1 = baseline_random_freq(1000, 0.5, seed=42)
        pred2 = baseline_random_freq(1000, 0.5, seed=99)
        assert not np.array_equal(pred1, pred2)

    def test_simple_rule_warns_on_negative_returns(self):
        returns = pd.Series([0.01, -0.03, -0.01, 0.02, -0.05])
        pred = baseline_simple_rule(returns, threshold=-0.02)
        expected = [False, True, False, False, True]
        np.testing.assert_array_equal(pred, expected)

    def test_simple_rule_custom_threshold(self):
        returns = pd.Series([0.01, -0.03, -0.01, 0.02, -0.05])
        pred = baseline_simple_rule(returns, threshold=-0.04)
        expected = [False, False, False, False, True]
        np.testing.assert_array_equal(pred, expected)


class TestComputeMetrics:
    """Test that metric computation is correct."""

    def test_perfect_predictions(self):
        pred = np.array([True, True, False, False])
        actual = np.array([True, True, False, False])
        m = compute_metrics(pred, actual, "test")
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["f1"] == 1.0
        assert m["accuracy"] == 1.0
        assert m["false_alarm_rate"] == 0.0
        assert m["missed_stress_rate"] == 0.0

    def test_all_false_predictions(self):
        pred = np.array([False, False, False, False])
        actual = np.array([True, True, False, False])
        m = compute_metrics(pred, actual, "test")
        assert m["precision"] == 0.0  # no predictions
        assert m["recall"] == 0.0     # missed all
        assert m["f1"] == 0.0
        assert m["missed_stress_rate"] == 1.0

    def test_all_true_predictions(self):
        pred = np.array([True, True, True, True])
        actual = np.array([True, True, False, False])
        m = compute_metrics(pred, actual, "test")
        assert m["precision"] == 0.5   # 2/4 correct
        assert m["recall"] == 1.0      # caught all stress
        assert m["false_alarm_rate"] == 1.0  # all calm flagged

    def test_mixed_predictions(self):
        pred = np.array([True, False, True, False])
        actual = np.array([True, True, False, False])
        m = compute_metrics(pred, actual, "test")
        assert m["tp"] == 1
        assert m["fp"] == 1
        assert m["fn"] == 1
        assert m["tn"] == 1
        assert m["precision"] == 0.5
        assert m["recall"] == 0.5

    def test_empty_predictions(self):
        pred = np.array([], dtype=bool)
        actual = np.array([], dtype=bool)
        m = compute_metrics(pred, actual, "test")
        assert m["n"] == 0
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0


# =========================================================================
# Threshold review bridge tests
# =========================================================================

class TestThresholdReviewBridge:
    """Test that threshold review candidates are generated correctly."""

    def test_no_cases_returns_no_candidates(self):
        # Monkey-patch load_missed_stress_cases to return empty
        import scripts.threshold_review_bridge as bridge
        original = bridge.load_missed_stress_cases
        bridge.load_missed_stress_cases = lambda: []
        try:
            report = build_review_candidates([])
            assert report["candidate_count"] == 0
            assert report["status"] == "no_candidates"
        finally:
            bridge.load_missed_stress_cases = original

    def test_candidates_include_current_thresholds(self):
        cases = [
            {
                "sample_id": "test_001",
                "as_of_date": "2026-06-15",
                "sample_type": "stress_window",
                "auto_label_reason": "missed stress",
                "system_judgment": {
                    "decision": "NO_TRADE",
                    "confidence": "low",
                    "claim_tier": 0,
                },
                "system_state": {
                    "m_value": 0.1,
                    "d_value": -0.2,
                    "k_value": 0.3,
                    "x_value": 0.0,
                },
                "forward_outcome": {
                    "spy": {"pct_1w": -0.05, "pct_1m": -0.08},
                    "max_drawdown_1m": -0.07,
                    "vix": {"change_1w": 8.0},
                    "stress_event_happened": True,
                },
            },
        ]
        report = build_review_candidates(cases)
        assert report["candidate_count"] == 1
        candidate = report["candidates"][0]
        assert "current_thresholds" in candidate
        assert candidate["current_thresholds"]["spy_1w_drop"] == -0.03
        assert candidate["current_thresholds"]["mdd_warning"] == -0.05

    def test_pattern_clusters_created(self):
        cases = [
            {
                "sample_id": f"test_{i}",
                "as_of_date": f"2026-06-{15+i}",
                "sample_type": "stress_window",
                "system_judgment": {"decision": "NO_TRADE", "confidence": "low", "claim_tier": 0},
                "system_state": {"m_value": 0.5, "k_value": 0.5},
                "forward_outcome": {
                    "spy": {"pct_1w": -0.05},
                    "max_drawdown_1m": -0.07,
                },
            }
            for i in range(3)
        ]
        report = build_review_candidates(cases)
        assert len(report["pattern_clusters"]) > 0
        # All cases should be in the same cluster (m_high_k_high)
        cluster = report["pattern_clusters"].get("m_high_k_high")
        assert cluster is not None
        assert cluster["count"] == 3

    def test_review_status_is_pending(self):
        cases = [
            {
                "sample_id": "test_001",
                "as_of_date": "2026-06-15",
                "sample_type": "stress_window",
                "system_judgment": {"decision": "NO_TRADE", "confidence": "low", "claim_tier": 0},
                "system_state": {"m_value": 0.0, "k_value": 0.0},
                "forward_outcome": {"spy": {"pct_1w": -0.05}, "max_drawdown_1m": -0.07},
            },
        ]
        report = build_review_candidates(cases)
        assert report["status"] == "pending_review"
        for candidate in report["candidates"]:
            assert candidate["review_status"] == "pending"
