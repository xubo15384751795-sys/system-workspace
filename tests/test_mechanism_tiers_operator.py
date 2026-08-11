"""Operator-bound mechanism tier engine/resolver tests.

Requires Data/nlp/caselab_training/mechanism_tiers.yaml (+ features).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.operator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nlp.caselab.event_trigger import EventTriggerEngine
from nlp.caselab.mechanism_resolver import MechanismResolver


class TestEventTriggerEngine(unittest.TestCase):
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
        self.assertIn("Margin Call", result.mechanism_names())

    def test_margin_call_not_triggered(self) -> None:
        obs = {"dd_vel_SPY_5d": 0.01, "rv_SPY_20d": 0.10}
        result = self.engine.evaluate(obs)
        self.assertNotIn("Margin Call", result.mechanism_names())

    def test_settlement_fail_triggered(self) -> None:
        obs = {"settlement_fail_count": 2}
        result = self.engine.evaluate(obs)
        self.assertIn("Settlement Fail", result.mechanism_names())

    def test_collateral_management_triggered(self) -> None:
        obs = {"haircut_change": 0.08}
        result = self.engine.evaluate(obs)
        self.assertIn("Collateral Management", result.mechanism_names())

    def test_clearing_triggered(self) -> None:
        obs = {"ccp_waterfall_activated": True}
        result = self.engine.evaluate(obs)
        self.assertIn("Clearing", result.mechanism_names())

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


class TestMechanismResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = MechanismResolver()

    def test_signal_tier_activation(self) -> None:
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
        self.assertIn("Liquidity Spiral", names)

    def test_event_tier_activation(self) -> None:
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30}
        result = self.resolver.resolve(observables=obs)
        self.assertGreater(len(result.event_activated), 0)

    def test_knowledge_tier_filtering(self) -> None:
        result = self.resolver.resolve(narrative_keywords=["ai", "compute", "platform"])
        self.assertGreater(len(result.knowledge_context), 0)
        names = [m.name for m in result.knowledge_context]
        ai_knowledge = [
            n
            for n in names
            if any(kw in n.lower() for kw in ["agent", "foundation", "scaling", "api", "gpu"])
        ]
        self.assertGreater(len(ai_knowledge), 0)

    def test_full_resolution(self) -> None:
        features = {"rv_SPY_20d": 0.30, "ratio_HYG_TLT": 0.42, "dd_vel_SPY_5d": 0.04}
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30, "haircut_change": 0.08}
        kw = ["liquidity", "margin", "credit"]
        result = self.resolver.resolve(
            market_features=features, observables=obs, narrative_keywords=kw
        )
        self.assertGreater(len(result.signal_activated), 0)
        self.assertGreater(len(result.event_activated), 0)
        self.assertGreater(len(result.knowledge_context), 0)
        self.assertGreater(result.total_activated, 0)

    def test_calm_scenario(self) -> None:
        features = {
            "rv_SPY_20d": 0.08,
            "ratio_HYG_TLT": 0.52,
            "corr_SPY_TLT_60d": 0.10,
            "dd_vel_SPY_5d": 0.005,
        }
        obs = {"dd_vel_SPY_5d": 0.005, "rv_SPY_20d": 0.08}
        result = self.resolver.resolve(market_features=features, observables=obs)
        stress_features = {
            "rv_SPY_20d": 0.30,
            "ratio_HYG_TLT": 0.42,
            "corr_SPY_TLT_60d": -0.65,
            "dd_vel_SPY_5d": 0.04,
        }
        stress_obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30, "haircut_change": 0.08}
        stress_result = self.resolver.resolve(
            market_features=stress_features, observables=stress_obs
        )
        self.assertLess(result.total_activated, stress_result.total_activated)
        self.assertEqual(len(result.event_activated), 0)

    def test_summary_structure(self) -> None:
        result = self.resolver.resolve()
        summary = result.summary()
        self.assertIn("signal_count", summary)
        self.assertIn("event_count", summary)
        self.assertIn("knowledge_count", summary)
        self.assertIn("total_activated", summary)

    def test_cascade_candidates(self) -> None:
        obs = {"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30}
        result = self.resolver.resolve(observables=obs)
        if result.event_activated:
            related = result.related_mechanism_names()
            self.assertIsInstance(related, list)


if __name__ == "__main__":
    unittest.main()
