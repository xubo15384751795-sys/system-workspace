from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.build_embeddings import build_from_index
from caselab_context.embeddings_core import build_embeddings, search
from caselab_context.graph_core import build_graph, extract_links, wikilink_targets
from caselab_context.graph_expand import expand_with_graph
from caselab_context.index_paper import build_index
from caselab_context.resolve_meaning import build_context_packet


class GraphCoreTests(unittest.TestCase):
    def test_wikilink_targets_from_list(self) -> None:
        targets = wikilink_targets(["[[Risk Transfer]]", "[[Balance Sheet Expansion]]"])
        self.assertEqual(targets, ["Risk Transfer", "Balance Sheet Expansion"])

    def test_extract_links_from_mechanisms(self) -> None:
        links = extract_links({"mechanisms": ["[[Risk Transfer]]", "[[Reflexivity]]"]})
        relations = {link["relation"] for link in links}
        self.assertEqual(relations, {"exhibits"})

    def test_graph_edges_resolve_by_title(self) -> None:
        records = [
            {
                "id": "01_Cases/IPO/Goldman Sachs IPO 1999.md",
                "title": "Goldman Sachs IPO 1999",
                "aliases": [],
                "links": [{"target": "Risk Transfer", "relation": "exhibits"}],
            },
            {
                "id": "03_Mechanisms/Finance/Risk Transfer.md",
                "title": "Risk Transfer",
                "aliases": [],
                "links": [],
            },
        ]
        graph = build_graph(records)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["relation"], "exhibits")


class GraphExpandTests(unittest.TestCase):
    def test_expand_adds_neighbor_with_decay(self) -> None:
        docs = [
            {"id": "a.md", "title": "A", "text": "alpha"},
            {"id": "b.md", "title": "B", "text": "beta"},
        ]
        graph = {"edges": [{"from": "a.md", "to": "b.md", "relation": "exhibits"}]}
        expanded = expand_with_graph(
            [{"id": "a.md", "title": "A", "text": "alpha", "score": 0.8}],
            graph,
            docs,
            max_hops=1,
        )
        titles = {item["title"] for item in expanded}
        self.assertIn("B", titles)

    def test_two_hop_chain_reaches_variable(self) -> None:
        docs = [
            {"id": "case.md", "title": "Case", "text": "case", "type": "case"},
            {"id": "mech.md", "title": "Mechanism", "text": "mech", "type": "mechanism"},
            {"id": "var.md", "title": "Variable", "text": "var", "type": "variable"},
        ]
        graph = {
            "edges": [
                {"from": "case.md", "to": "mech.md", "relation": "exhibits"},
                {"from": "mech.md", "to": "var.md", "relation": "defines"},
            ]
        }
        expanded = expand_with_graph(
            [{"id": "case.md", "title": "Case", "text": "case", "score": 1.0}],
            graph,
            docs,
            max_hops=2,
        )
        titles = {item["title"] for item in expanded}
        self.assertIn("Mechanism", titles)
        self.assertIn("Variable", titles)


class QualityWeightTests(unittest.TestCase):
    def test_core_beats_seed(self) -> None:
        from caselab_context.quality_weights import quality_bonus

        self.assertGreater(quality_bonus("core"), quality_bonus("seed"))
        self.assertGreater(quality_bonus("useful"), quality_bonus("seed"))


class EmbeddingTests(unittest.TestCase):
    def test_build_and_search_embeddings(self) -> None:
        records = build_index()[:50]
        payload = build_from_index(records, backend="tfidf")
        self.assertIn("graph", payload)
        results = search(payload, "Goldman IPO risk transfer", top_k=3)
        self.assertTrue(results)
        titles = " ".join(item["title"] for item in results).lower()
        self.assertTrue("goldman" in titles or "ipo" in titles)

    def test_hybrid_payload_keeps_sparse_vectors(self) -> None:
        records = build_index()[:10]
        payload = build_embeddings(records, backend="tfidf")
        self.assertEqual(payload["backend"], "tfidf")
        self.assertTrue(payload["sparse_vectors"])

    def test_context_packet_includes_similar_notes(self) -> None:
        from caselab_context.build_embeddings import EMBEDDINGS_PATH, save_embeddings

        records = build_index()[:100]
        save_embeddings(EMBEDDINGS_PATH, build_from_index(records, backend="tfidf"))
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
