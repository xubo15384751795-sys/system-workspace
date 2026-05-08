"""Test: Learning Hub events must NOT contain raw Qlib payload."""

import json
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "Workbench" / "src"))

from benchmarks.market_feedback.report_writer import build_benchmark_event


class TestLearningEventBoundary:
    def test_event_does_not_include_raw_qlib_payload(self):
        """Benchmark events must exclude predictions, positions, cache, models."""
        event = build_benchmark_event("test_benchmark_learning_boundary")

        forbidden_keys = {"predictions", "raw_positions", "qlib_cache", "raw_model"}
        for key in forbidden_keys:
            assert key not in event, (
                f"Learning Hub event must not contain raw Qlib key: {key}"
            )

    def test_event_has_required_fields(self):
        event = build_benchmark_event("test_benchmark_learning_boundary")
        assert "event_type" in event
        assert event["event_type"] == "market_feedback_benchmark_completed"
        assert "benchmark_id" in event
        assert "executor" in event
        assert "feedback_type" in event
        assert "metric_deltas" in event
        assert "recommended_action" in event

    def test_event_executor_is_qlib(self):
        event = build_benchmark_event("test_benchmark_learning_boundary")
        assert event["executor"] == "qlib"

    def test_event_can_be_serialized(self):
        event = build_benchmark_event("test_benchmark_learning_boundary")
        serialized = json.dumps(event)
        reloaded = json.loads(serialized)
        assert reloaded == event

    def test_event_is_not_raw_qlib_output(self):
        """The event is a structured summary, not raw experiment output."""
        event = build_benchmark_event("test_benchmark_learning_boundary")
        # Event should NOT contain raw experiment data like per-stock predictions
        assert "per_stock_predictions" not in event
        assert "backtest_portfolio_weights" not in event
        assert "model_parameters" not in event
