from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.operator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.quality_weights import filter_by_min_quality, passes_min_quality
from caselab_context.reference_chains import (
    load_reference_chains,
    reference_chain_boost,
)
from caselab_context.regime_from_indicators import infer_regime_from_indicators
from caselab_context.world_model import query


class RegimeInferenceTests(unittest.TestCase):
    def test_infer_regime_from_processed_data(self) -> None:
        payload = infer_regime_from_indicators()
        self.assertIn("regime", payload)
        regime = payload["regime"]
        self.assertIn(regime["liquidity"], {"abundant", "tightening", "stressed"})
        self.assertIn(regime["credit"], {"expanding", "fragile", "contracting"})
        self.assertTrue(payload.get("evidence"))

    def test_indicator_snapshot_has_fred_values(self) -> None:
        payload = infer_regime_from_indicators()
        snap = payload.get("indicator_snapshot") or {}
        self.assertIn("SOFR", snap)
        self.assertIn("High Yield OAS", snap)


class QualityFilterTests(unittest.TestCase):
    def test_min_quality_filters_seed(self) -> None:
        rows = [
            {"title": "A", "quality": "seed", "score": 0.9},
            {"title": "B", "quality": "useful", "score": 0.5},
        ]
        filtered = filter_by_min_quality(rows, "useful")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "B")

    def test_passes_min_quality_ranking(self) -> None:
        self.assertTrue(passes_min_quality("core", "useful"))
        self.assertFalse(passes_min_quality("seed", "useful"))


class ReferenceChainTests(unittest.TestCase):
    def test_reference_chains_loaded(self) -> None:
        chains = load_reference_chains()
        self.assertGreaterEqual(len(chains), 2)

    def test_reference_boost_for_goldman_case(self) -> None:
        self.assertGreater(reference_chain_boost("Goldman Sachs IPO 1999"), 0.0)


class WorldModelQueryTests(unittest.TestCase):
    def test_world_model_query_goldman_ipo(self) -> None:
        response = query(
            "Goldman Sachs",
            "ipo",
            "public_market",
            use_indicator_regime=True,
            min_quality="useful",
        )
        self.assertIn("gs_ipo_risk_transfer", response.context_packet["matched_rules"])
        self.assertIn(response.regime_source, {"indicators", "indicators+paper", "default"})
        self.assertIsInstance(response.warnings, list)

    def test_similar_notes_respect_min_quality(self) -> None:
        response = query(
            "Goldman Sachs",
            "ipo",
            "public_market",
            min_quality="useful",
            use_indicator_regime=False,
        )
        for item in response.context_packet.get("similar_notes") or []:
            self.assertTrue(passes_min_quality(item.get("quality"), "useful"))


if __name__ == "__main__":
    unittest.main()
