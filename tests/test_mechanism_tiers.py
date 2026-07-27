"""Pure condition-evaluator unit tests for mechanism tiers (hermetic).

EventTriggerEngine / MechanismResolver need Data/nlp/caselab_training YAML and
live in test_mechanism_tiers_operator.py.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nlp.caselab.event_trigger import evaluate_condition


class TestConditionEvaluator(unittest.TestCase):
    """Test the boolean expression evaluator."""

    def test_simple_gt(self) -> None:
        self.assertTrue(evaluate_condition("dd_vel_SPY_5d > 0.03", {"dd_vel_SPY_5d": 0.04}))
        self.assertFalse(evaluate_condition("dd_vel_SPY_5d > 0.03", {"dd_vel_SPY_5d": 0.02}))

    def test_simple_eq(self) -> None:
        self.assertTrue(evaluate_condition("flag == True", {"flag": True}))
        self.assertFalse(evaluate_condition("flag == True", {"flag": False}))

    def test_and_connective(self) -> None:
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30}
        self.assertTrue(
            evaluate_condition("(dd_vel_SPY_5d > 0.03) AND (rv_SPY_20d > 0.25)", obs)
        )
        obs["rv_SPY_20d"] = 0.20
        self.assertFalse(
            evaluate_condition("(dd_vel_SPY_5d > 0.03) AND (rv_SPY_20d > 0.25)", obs)
        )

    def test_or_connective(self) -> None:
        obs = {"settlement_fail_count": 0, "delivery_failure_flag": True}
        self.assertTrue(
            evaluate_condition(
                "settlement_fail_count > 0 OR delivery_failure_flag == True", obs
            )
        )
        obs["delivery_failure_flag"] = False
        self.assertFalse(
            evaluate_condition(
                "settlement_fail_count > 0 OR delivery_failure_flag == True", obs
            )
        )

    def test_missing_variable_defaults_zero(self) -> None:
        self.assertFalse(evaluate_condition("unknown_var > 5", {}))

    def test_complex_expression(self) -> None:
        obs = {"treasury_basis_spread": 3.5, "leverage_ratio": 15.0}
        self.assertTrue(
            evaluate_condition("treasury_basis_spread > 2 AND leverage_ratio > 10", obs)
        )

    def test_ge_le_operators(self) -> None:
        self.assertTrue(evaluate_condition("x >= 5", {"x": 5}))
        self.assertTrue(evaluate_condition("x <= 5", {"x": 5}))
        self.assertFalse(evaluate_condition("x >= 6", {"x": 5}))


if __name__ == "__main__":
    unittest.main()
