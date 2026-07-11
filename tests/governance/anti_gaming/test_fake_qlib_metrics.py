"""Anti-gaming test: Qlib benchmark metrics that look real but aren't.

A common failure pattern: a Qlib run produces structured-looking metrics
JSON, but those metrics are zero/null because Qlib was never installed or
the executor short-circuited.  Downstream promotion gates must reject
these as "feedback_blocked / inconclusive" rather than treating them as
valid alpha evidence.

This test loads the validator from the isolated runner and asserts it
rejects three indistinguishable-from-no-op shapes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER_DIR = ROOT / "ExternalTools" / "qlib_benchmark_runner"
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

from run_qlib_benchmark import validate_benchmark_metrics


def test_all_null_metrics_are_rejected() -> None:
    metrics = {
        "experiment": "treatment",
        "config": "lgb_alpha158",
        "executor_status": "qlib_real",  # claims real but values are null
        "placeholder": False,
        "feedback_blocked": False,
        "rank_ic": None,
        "rank_icir": None,
        "sharpe": None,
        "max_drawdown": None,
        "annual_return": None,
        "information_ratio": None,
    }
    with pytest.raises(ValueError, match="benchmark was not executed"):
        validate_benchmark_metrics(metrics)


def test_all_zero_metrics_without_placeholder_marker_are_rejected() -> None:
    metrics = {
        "experiment": "treatment",
        "config": "lgb_alpha158",
        "executor_status": "qlib_real",
        "placeholder": False,
        "feedback_blocked": False,
        "rank_ic": 0.0,
        "rank_icir": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "annual_return": 0.0,
        "information_ratio": 0.0,
    }
    with pytest.raises(ValueError, match="indistinguishable from the no-qlib placeholder"):
        validate_benchmark_metrics(metrics)


def test_placeholder_marked_metrics_are_accepted_for_caller_decision() -> None:
    """Explicit placeholder markers bypass validation so the caller can
    decide whether to ignore (the runner's intended contract)."""
    metrics = {
        "experiment": "treatment",
        "config": "lgb_alpha158",
        "executor_status": "placeholder_no_qlib",
        "placeholder": True,
        "feedback_blocked": True,
        "rank_ic": None,
        "rank_icir": None,
        "sharpe": None,
        "max_drawdown": None,
        "annual_return": None,
        "information_ratio": None,
    }
    validate_benchmark_metrics(metrics)


def test_real_alpha_metrics_pass() -> None:
    metrics = {
        "experiment": "treatment",
        "config": "lgb_alpha158",
        "executor_status": "qlib_real",
        "placeholder": False,
        "feedback_blocked": False,
        "rank_ic": 0.045,
        "rank_icir": 0.32,
        "sharpe": 1.2,
        "max_drawdown": -0.15,
        "annual_return": 0.18,
        "information_ratio": 0.85,
    }
    validate_benchmark_metrics(metrics)
