"""Golden samples: strict acceptance criteria for Contextual Meaning Resolver.

Each sample must pass ALL of:
  1. matched_rule contains the expected rule ID
  2. risk_transfer.from and .to are non-empty
  3. non_transferable_conditions is non-empty
  4. next_checks is non-empty (actionable follow-ups)
  5. similar_notes has at least 1 entry with score > 0
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.build_embeddings import (
    EMBEDDINGS_PATH,
    build_from_index,
    save_embeddings,
)
from caselab_context.index_paper import build_index
from caselab_context.resolve_meaning import build_context_packet

# Ensure embeddings exist for similar_notes tests
_records = build_index()
save_embeddings(EMBEDDINGS_PATH, build_from_index(_records, backend="tfidf"))

FULL_REGIME = {
    "liquidity": "abundant",
    "rates": "stable",
    "credit": "expanding",
    "regulation": "loose",
    "market_mood": "risk_on",
    "technology_cycle": "scaling",
}


def _regime(**overrides: str) -> dict[str, str]:
    return {**FULL_REGIME, **overrides}


def _build(actor: str, verb: str, obj: str, regime: dict[str, str]) -> dict:
    return build_context_packet(actor, verb, obj, regime)


def _meaning(packet: dict) -> dict:
    return packet["context_packet"]["contextual_meaning"]


def _assert_packet_valid(
    test: unittest.TestCase,
    packet: dict,
    expected_rule: str,
) -> None:
    ctx = packet["context_packet"]

    # 1. matched_rule correct
    test.assertIn(expected_rule, ctx["matched_rules"], f"Expected rule '{expected_rule}' in {ctx['matched_rules']}")

    # 2. risk_transfer non-empty
    rt = _meaning(packet).get("risk_transfer") or {}
    test.assertTrue(rt.get("from"), "risk_transfer.from must be non-empty")
    test.assertTrue(rt.get("to"), "risk_transfer.to must be non-empty")

    # 3. non_transferable_conditions non-empty
    ntc = _meaning(packet).get("non_transferable_conditions") or []
    test.assertTrue(len(ntc) > 0, "non_transferable_conditions must be non-empty")

    # 4. next_checks non-empty and actionable
    nc = _meaning(packet).get("next_checks") or []
    test.assertTrue(len(nc) > 0, "next_checks must be non-empty")

    # 5. similar_notes at least 1 reasonable result
    similar = ctx.get("similar_notes") or []
    test.assertTrue(len(similar) > 0, "similar_notes must have at least 1 entry")
    test.assertGreater(similar[0]["score"], 0, "Top similar note score must be > 0")


class GoldenSamplesGoldmanIPO(unittest.TestCase):
    """Goldman Sachs IPO 1999 — partnership → public shareholders."""

    def test_goldman_ipo(self) -> None:
        packet = _build("Goldman Sachs", "ipo", "public_market", _regime())
        _assert_packet_valid(self, packet, "gs_ipo_risk_transfer")
        self.assertIn("partners", _meaning(packet)["risk_transfer"]["from"])


class GoldenSamplesGoldmanAIAbundant(unittest.TestCase):
    """Goldman AI financing under abundant liquidity — growth signal."""

    def test_goldman_ai_financing_abundant(self) -> None:
        packet = _build(
            "Goldman Sachs", "arrange_financing", "ai_data_center",
            _regime(liquidity="abundant", credit="expanding", technology_cycle="scaling"),
        )
        _assert_packet_valid(self, packet, "gs_financing_ai_abundant")
        self.assertIn("financeable", _meaning(packet)["deeper_structure"])


class GoldenSamplesGoldmanAITight(unittest.TestCase):
    """Goldman AI financing under tight liquidity — risk packaging signal."""

    def test_goldman_ai_financing_tight(self) -> None:
        packet = _build(
            "Goldman Sachs", "arrange_financing", "ai_data_center",
            _regime(liquidity="tightening", credit="fragile"),
        )
        _assert_packet_valid(self, packet, "gs_financing_ai_tight")
        self.assertIn("packaged", _meaning(packet)["deeper_structure"])


class GoldenSamplesFedTightening(unittest.TestCase):
    """Fed rate tightening — duration and leverage pressure."""

    def test_fed_tightening(self) -> None:
        packet = _build(
            "Federal Reserve", "tightening", "federal_funds",
            _regime(rates="rising", market_mood="risk_off"),
        )
        _assert_packet_valid(self, packet, "fed_rate_tightening")
        self.assertIn("borrowers", _meaning(packet)["risk_transfer"]["from"])


class GoldenSamplesFedLiquidityInjection(unittest.TestCase):
    """Fed liquidity injection — systemic risk socialization."""

    def test_fed_liquidity_injection(self) -> None:
        packet = _build(
            "Federal Reserve", "injecting", "liquidity",
            _regime(liquidity="stressed", market_mood="crisis"),
        )
        _assert_packet_valid(self, packet, "fed_liquidity_injection")
        self.assertIn("central bank", _meaning(packet)["deeper_structure"])


class GoldenSamplesJPMDistressedAcquisition(unittest.TestCase):
    """JPMorgan acquires distressed bank in crisis — TBTF consolidation."""

    def test_jpm_crisis_acquisition(self) -> None:
        packet = _build(
            "JPMorgan Chase", "acquiring", "distressed_bank",
            _regime(liquidity="stressed", market_mood="crisis"),
        )
        _assert_packet_valid(self, packet, "jpm_crisis_acquisition")
        self.assertIn("consolidation", _meaning(packet)["deeper_structure"])


class GoldenSamplesNvidiaExportControl(unittest.TestCase):
    """Nvidia export restriction — policy repricing market access."""

    def test_nvidia_export_control(self) -> None:
        packet = _build(
            "Nvidia", "export_control", "china",
            _regime(regulation="tightening"),
        )
        _assert_packet_valid(self, packet, "nv_export_restriction")
        self.assertIn("policy", _meaning(packet)["deeper_structure"])


class GoldenSamplesOpenAIPOPrep(unittest.TestCase):
    """OpenAI IPO preparation — private AI risk → public market."""

    def test_openai_ipo_preparation(self) -> None:
        packet = _build(
            "OpenAI", "ipo", "public_market",
            _regime(liquidity="abundant", technology_cycle="scaling"),
        )
        _assert_packet_valid(self, packet, "oai_ipo_preparation")
        self.assertIn("private", _meaning(packet)["deeper_structure"])


if __name__ == "__main__":
    unittest.main()
