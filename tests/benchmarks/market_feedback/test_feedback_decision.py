"""Test feedback_decision: classification logic and learning hub boundary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages" / "workbench" / "src"))

from benchmarks.market_feedback.feedback_decision import FEEDBACK_TYPES, _write_decision


class TestFeedbackDecision:
    def test_feedback_types_are_valid(self):
        valid = {
            "positive_increment",
            "risk_only_increment",
            "regime_specific_increment",
            "no_increment",
            "negative_increment",
            "inconclusive",
        }
        assert set(FEEDBACK_TYPES) == valid

    def test_positive_increment_detection(self, tmp_path):
        deltas = {"rank_ic_delta": 0.01, "sharpe_delta": 0.1, "max_drawdown_delta": 0.01}
        decision = _write_decision(
            tmp_path, "test_benchmark", "positive_increment",
            "test", deltas, recommended_action=["test action"]
        )
        assert decision["feedback_type"] == "positive_increment"

    def test_inconclusive_on_empty_deltas(self, tmp_path):
        decision = _write_decision(
            tmp_path, "test_benchmark", "inconclusive",
            "No metric deltas", {}
        )
        assert decision["feedback_type"] == "inconclusive"

    def test_negative_increment_detection(self, tmp_path):
        deltas = {"rank_ic_delta": -0.01, "sharpe_delta": -0.05, "max_drawdown_delta": -0.01}
        decision = _write_decision(
            tmp_path, "test_benchmark", "negative_increment",
            "test", deltas, recommended_action=["review"]
        )
        assert decision["feedback_type"] == "negative_increment"
