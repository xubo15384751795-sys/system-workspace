from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.operator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.mcp_server import (
    get_current_regime,
    get_entity_dna,
    resolve_context,
    search_similar_notes,
)


class McpToolTests(unittest.TestCase):
    def test_resolve_context_returns_packet(self) -> None:
        payload = json.loads(
            resolve_context(
                actor="Goldman Sachs",
                verb="ipo",
                action_object="public_market",
            )
        )
        self.assertIn("context_packet", payload)
        self.assertIn("gs_ipo_risk_transfer", payload["context_packet"]["matched_rules"])

    def test_get_entity_dna(self) -> None:
        payload = json.loads(get_entity_dna("Goldman Sachs"))
        self.assertEqual(payload["entity"], "Goldman Sachs")

    def test_get_current_regime(self) -> None:
        payload = json.loads(get_current_regime())
        self.assertIn("regime", payload)
        self.assertIn("liquidity", payload["regime"])

    def test_search_similar_notes(self) -> None:
        with patch("caselab_context.mcp_server.retrieve_similar_reranked", return_value=[{"title": "X", "score": 0.5}]):
            payload = json.loads(search_similar_notes("Goldman IPO", top_k=3))
        self.assertEqual(payload["query"], "Goldman IPO")
        self.assertEqual(len(payload["results"]), 1)


if __name__ == "__main__":
    unittest.main()
