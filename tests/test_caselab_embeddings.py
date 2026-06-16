from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.build_embeddings import build_from_index
from caselab_context.embeddings_core import search
from caselab_context.index_paper import build_index
from caselab_context.resolve_meaning import build_context_packet


class EmbeddingTests(unittest.TestCase):
    def test_build_and_search_embeddings(self) -> None:
        records = build_index()[:50]
        payload = build_from_index(records)
        results = search(payload, "Goldman IPO risk transfer", top_k=3)
        self.assertTrue(results)
        titles = " ".join(item["title"] for item in results).lower()
        self.assertTrue("goldman" in titles or "ipo" in titles)

    def test_context_packet_includes_similar_notes(self) -> None:
        from caselab_context.build_embeddings import EMBEDDINGS_PATH, build_from_index, save_embeddings
        from caselab_context.index_paper import build_index

        records = build_index()[:100]
        save_embeddings(EMBEDDINGS_PATH, build_from_index(records))
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
        self.assertIn("similar_notes", packet["context_packet"])


if __name__ == "__main__":
    unittest.main()
