"""Tests for three-tier mechanism activation.

Verifies:
  1. Event trigger condition evaluation
  2. Signal-tier activation from market features
  3. Event-tier activation from observables
  4. Knowledge-tier filtering by narrative keywords
  5. Unified resolver combining all three tiers
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nlp.caselab.event_trigger import (
    EventTriggerEngine,
    evaluate_condition,
)
from nlp.caselab.mechanism_resolver import MechanismResolver


# ── Condition evaluator unit tests ──────────────────────────────────────

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
        self.assertTrue(evaluate_condition(
            "(dd_vel_SPY_5d > 0.03) AND (rv_SPY_20d > 0.25)", obs,
        ))
        obs["rv_SPY_20d"] = 0.20
        self.assertFalse(evaluate_condition(
            "(dd_vel_SPY_5d > 0.03) AND (rv_SPY_20d > 0.25)", obs,
        ))

    def test_or_connective(self) -> None:
        obs = {"settlement_fail_count": 0, "delivery_failure_flag": True}
        self.assertTrue(evaluate_condition(
            "settlement_fail_count > 0 OR delivery_failure_flag == True", obs,
        ))
        obs["delivery_failure_flag"] = False
        self.assertFalse(evaluate_condition(
            "settlement_fail_count > 0 OR delivery_failure_flag == True", obs,
        ))

    def test_missing_variable_defaults_zero(self) -> None:
        self.assertFalse(evaluate_condition("unknown_var > 5", {}))

    def test_complex_expression(self) -> None:
        obs = {
            "treasury_basis_spread": 3.5,
            "leverage_ratio": 15.0,
        }
        self.assertTrue(evaluate_condition(
            "treasury_basis_spread > 2 AND leverage_ratio > 10", obs,
        ))

    def test_ge_le_operators(self) -> None:
        self.assertTrue(evaluate_condition("x >= 5", {"x": 5}))
        self.assertTrue(evaluate_condition("x <= 5", {"x": 5}))
        self.assertFalse(evaluate_condition("x >= 6", {"x": 5}))


# ── Event trigger engine tests ──────────────────────────────────────────

class TestEventTriggerEngine(unittest.TestCase):
    """Test the event trigger engine against mechanism_tiers.yaml."""

    def setUp(self) -> None:
        self.engine = EventTriggerEngine()

    def test_loads_all_event_mechanisms(self) -> None:
        mechs = self.engine.event_mechanisms
        self.assertEqual(len(mechs), 14)
        self.assertIn("Margin Call", mechs)
        self.assertIn("Settlement Fail", mechs)
        self.assertIn("Clearing", mechs)

    def test_margin_call_triggered(self) -> None:
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30}
        result = self.engine.evaluate(obs)
        names = result.mechanism_names()
        self.assertIn("Margin Call", names)

    def test_margin_call_not_triggered(self) -> None:
        obs = {"dd_vel_SPY_5d": 0.01, "rv_SPY_20d": 0.10}
        result = self.engine.evaluate(obs)
        names = result.mechanism_names()
        self.assertNotIn("Margin Call", names)

    def test_settlement_fail_triggered(self) -> None:
        obs = {"settlement_fail_count": 2}
        result = self.engine.evaluate(obs)
        names = result.mechanism_names()
        self.assertIn("Settlement Fail", names)

    def test_collateral_management_triggered(self) -> None:
        obs = {"haircut_change": 0.08}
        result = self.engine.evaluate(obs)
        names = result.mechanism_names()
        self.assertIn("Collateral Management", names)

    def test_clearing_triggered(self) -> None:
        obs = {"ccp_waterfall_activated": True}
        result = self.engine.evaluate(obs)
        names = result.mechanism_names()
        self.assertIn("Clearing", names)

    def test_stress_scenario_multiple_triggers(self) -> None:
        obs = {
            "dd_vel_SPY_5d": 0.04,
            "rv_SPY_20d": 0.30,
            "settlement_fail_count": 2,
            "haircut_change": 0.08,
            "leverage_ratio": 15.0,
            "treasury_basis_spread": 3.5,
        }
        result = self.engine.evaluate(obs)
        self.assertGreaterEqual(result.activation_count, 3)
        self.assertEqual(result.evaluated, 14)
        self.assertEqual(len(result.errors), 0)

    def test_calm_scenario_no_triggers(self) -> None:
        obs = {
            "dd_vel_SPY_5d": 0.005,
            "rv_SPY_20d": 0.08,
            "settlement_fail_count": 0,
            "haircut_change": 0.01,
        }
        result = self.engine.evaluate(obs)
        self.assertEqual(result.activation_count, 0)

    def test_related_mechanisms_populated(self) -> None:
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30}
        result = self.engine.evaluate(obs)
        for m in result.triggered:
            self.assertIsInstance(m.related_mechanisms, list)
            self.assertGreater(len(m.related_mechanisms), 0)


# ── Mechanism resolver integration tests ────────────────────────────────

class TestMechanismResolver(unittest.TestCase):
    """Test the unified three-tier resolver."""

    def setUp(self) -> None:
        self.resolver = MechanismResolver()

    def test_signal_tier_activation(self) -> None:
        """High volatility features should activate signal mechanisms."""
        features = {
            "rv_SPY_20d": 0.30,
            "rv_SPY_60d": 0.22,
            "corr_SPY_TLT_60d": -0.65,
            "ratio_HYG_TLT": 0.42,
            "dd_vel_SPY_5d": 0.04,
        }
        result = self.resolver.resolve(market_features=features)
        self.assertGreater(len(result.signal_activated), 0)
        names = [m.name for m in result.signal_activated]
        # Liquidity Spiral has these features
        self.assertIn("Liquidity Spiral", names)

    def test_event_tier_activation(self) -> None:
        """Discrete events should trigger event-tier mechanisms."""
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30}
        result = self.resolver.resolve(observables=obs)
        self.assertGreater(len(result.event_activated), 0)

    def test_knowledge_tier_filtering(self) -> None:
        """Narrative keywords should filter knowledge mechanisms."""
        result = self.resolver.resolve(
            narrative_keywords=["ai", "compute", "platform"],
        )
        self.assertGreater(len(result.knowledge_context), 0)
        names = [m.name for m in result.knowledge_context]
        # AI-related knowledge mechanisms should be present
        ai_knowledge = [n for n in names if any(
            kw in n.lower() for kw in ["agent", "foundation", "scaling", "api", "gpu"]
        )]
        self.assertGreater(len(ai_knowledge), 0)

    def test_full_resolution(self) -> None:
        """All three tiers should work together."""
        features = {
            "rv_SPY_20d": 0.30,
            "ratio_HYG_TLT": 0.42,
            "dd_vel_SPY_5d": 0.04,
        }
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30, "haircut_change": 0.08}
        kw = ["liquidity", "margin", "credit"]

        result = self.resolver.resolve(
            market_features=features,
            observables=obs,
            narrative_keywords=kw,
        )

        self.assertGreater(len(result.signal_activated), 0)
        self.assertGreater(len(result.event_activated), 0)
        self.assertGreater(len(result.knowledge_context), 0)
        self.assertGreater(result.total_activated, 0)

    def test_calm_scenario(self) -> None:
        """Calm market should produce fewer activations than stress."""
        features = {
            "rv_SPY_20d": 0.08,
            "ratio_HYG_TLT": 0.52,
            "corr_SPY_TLT_60d": 0.10,
            "dd_vel_SPY_5d": 0.005,
        }
        obs = {"dd_vel_SPY_5d": 0.005, "rv_SPY_20d": 0.08}
        result = self.resolver.resolve(
            market_features=features,
            observables=obs,
        )
        # Compare against stress scenario
        stress_features = {
            "rv_SPY_20d": 0.30,
            "ratio_HYG_TLT": 0.42,
            "corr_SPY_TLT_60d": -0.65,
            "dd_vel_SPY_5d": 0.04,
        }
        stress_obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30, "haircut_change": 0.08}
        stress_result = self.resolver.resolve(
            market_features=stress_features,
            observables=stress_obs,
        )
        # Calm should activate fewer mechanisms than stress
        self.assertLess(result.total_activated, stress_result.total_activated)
        # Event tier: no stress = no triggers
        self.assertEqual(len(result.event_activated), 0)

    def test_summary_structure(self) -> None:
        """Summary should have all expected fields."""
        result = self.resolver.resolve()
        summary = result.summary()
        self.assertIn("signal_count", summary)
        self.assertIn("event_count", summary)
        self.assertIn("knowledge_count", summary)
        self.assertIn("total_activated", summary)

    def test_cascade_candidates(self) -> None:
        """Event-triggered mechanisms should expose cascade candidates."""
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30}
        result = self.resolver.resolve(observables=obs)
        if result.event_activated:
            related = result.related_mechanism_names()
            self.assertIsInstance(related, list)


if __name__ == "__main__":
    unittest.main()
