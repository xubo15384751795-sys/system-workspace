from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.operator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.enrich_signal import enrich_trade_signal
from caselab_context.load_context import load_current_regime, load_entity_dna
from caselab_context.resolve_meaning import build_context_packet


class ContextLayerTests(unittest.TestCase):
    def test_goldman_entity_dna_loaded(self) -> None:
        entity = load_entity_dna("Goldman Sachs")
        self.assertEqual(entity["entity"], "Goldman Sachs")
        self.assertIn("risk_pricing", entity["context_layer"]["core_functions"])

    def test_goldman_ai_financing_rule(self) -> None:
        packet = build_context_packet(
            "Goldman Sachs",
            "arrange_financing",
            "ai_data_center",
            {
                "liquidity": "abundant",
                "credit": "expanding",
                "technology_cycle": "scaling",
                "rates": "stable",
                "regulation": "loose",
                "market_mood": "risk_on",
            },
        )
        rules = packet["context_packet"]["matched_rules"]
        self.assertIn("gs_financing_ai_abundant", rules)
        meaning = packet["context_packet"]["contextual_meaning"]
        self.assertIn("financeable", meaning["deeper_structure"])

    def test_nvidia_guidance_rule(self) -> None:
        packet = build_context_packet(
            "Nvidia",
            "raising_guidance",
            "data_center",
            {
                "technology_cycle": "scaling",
                "credit": "expanding",
                "liquidity": "abundant",
                "rates": "stable",
                "regulation": "loose",
                "market_mood": "risk_on",
            },
        )
        self.assertIn("nv_capex_scaling", packet["context_packet"]["matched_rules"])

    def test_current_regime_loaded(self) -> None:
        regime = load_current_regime()
        self.assertIsNotNone(regime)
        self.assertEqual(regime["technology_cycle"], "scaling")

    def test_default_rule_filtered_when_specific_exists(self) -> None:
        packet = build_context_packet(
            "Goldman Sachs",
            "ipo",
            "public_market",
            {
                "liquidity": "abundant",
                "rates": "stable",
                "credit": "expanding",
                "regulation": "loose",
                "market_mood": "risk_on",
                "technology_cycle": "scaling",
            },
        )
        ids = packet["context_packet"]["matched_rules"]
        self.assertIn("gs_ipo_risk_transfer", ids)
        self.assertNotIn("gs_default_financial_intermediation", ids)

    def test_nvda_trade_signal_enrichment(self) -> None:
        packet = enrich_trade_signal("NVDA", {"signal": "bullish"})
        rules = packet["context_packet"]["matched_rules"]
        self.assertTrue(
            any(rule in rules for rule in ("nv_capex_scaling", "nv_capex_saturation")),
            msg=f"expected capex rule, got {rules}",
        )


if __name__ == "__main__":
    unittest.main()
