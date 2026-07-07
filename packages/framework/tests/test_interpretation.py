from __future__ import annotations

import unittest

import numpy as np

from src.core.models import NarrativeReading, ProxyReading, Snapshot, StructuralState
from src.interpretation.market_state import classify_pattern, interpret_snapshot, leading_channel


def _snapshot(pattern: str = "PRE_SINGULAR") -> Snapshot:
    proxy = ProxyReading(
        run_date="2026-04-14",
        M=0.1,
        D=-0.8,
        K=0.9,
        X=0.2,
        directions={"M": "STABLE", "D": "WORSENING", "K": "WORSENING", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.1, "D": -0.8, "K": 0.9, "X": 0.2},
    )
    state = StructuralState(
        run_date="2026-04-14",
        z_vector=np.ones(6),
        sigma_t=1.0,
        singular_flag=False,
        leading_channel="D",
        pattern=pattern,
        anomaly_score=-0.1,
        reflexivity_flags={"credit": False},
        provenance={"code_version": "test"},
    )
    narrative = NarrativeReading(
        run_date="2026-04-14",
        ai_unicorn="ANCHORED",
        clo_cmbs="ANCHORED",
        policy="ANCHORED",
        drift_scores={},
    )
    return Snapshot(
        run_date="2026-04-14",
        run_type="WEEKLY",
        proxy=proxy,
        state=state,
        narrative=narrative,
        escalation=False,
        escalation_reason=None,
    )


class InterpretationTests(unittest.TestCase):
    def test_classifies_pre_singular_without_shadow_stress(self) -> None:
        directions = {"M": "STABLE", "D": "WORSENING", "K": "WORSENING", "X": "STABLE"}

        self.assertEqual(classify_pattern(directions), "PRE_SINGULAR")
        self.assertEqual(leading_channel(directions), "D")

    def test_reflexivity_overrides_channel_pattern(self) -> None:
        directions = {"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "WORSENING"}

        self.assertEqual(classify_pattern(directions, {"policy": True}), "REFLEXIVITY_LOOP")

    def test_interpret_snapshot_returns_explanatory_payload(self) -> None:
        interpretation = interpret_snapshot(_snapshot())

        self.assertEqual(interpretation.pattern, "PRE_SINGULAR")
        self.assertEqual(interpretation.severity, "ELEVATED")
        self.assertIn("D", interpretation.channel_notes)
        self.assertTrue(interpretation.recommended_actions)


if __name__ == "__main__":
    unittest.main()
