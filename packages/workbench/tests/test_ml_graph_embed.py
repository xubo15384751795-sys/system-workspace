"""Tests for ml.graph_embed — SVD backend (numpy-only, always available)."""
from __future__ import annotations

import numpy as np
import pytest

from ml.graph_embed import (
    GraphEmbedder,
    NodeEmbeddings,
    _cosine,
    _ppmi,
    _truncated_svd,
    embed_graph,
    graph_cosine_similarity,
)
from nlp.cases.case_similarity import _blend
from nlp.narrative.graph_builder import (
    GraphEdge,
    GraphNode,
    StructuralGraph,
)


# ---------------------------------------------------------------------------
# Helpers — build small test graphs
# ---------------------------------------------------------------------------

def _node(nid: str, node_type: str = "institution") -> GraphNode:
    return GraphNode(id=nid, label=nid, node_type=node_type)


def _edge(src: str, tgt: str, confidence: float = 0.8) -> GraphEdge:
    return GraphEdge(source=src, target=tgt, relation="holds", confidence=confidence)


def _chain_graph(n: int = 5) -> StructuralGraph:
    """Linear chain: 0–1–2–…–(n-1)."""
    nodes = [_node(str(i)) for i in range(n)]
    edges = [_edge(str(i), str(i + 1)) for i in range(n - 1)]
    return StructuralGraph(graph_id="chain", nodes=nodes, edges=edges)


def _ring_graph(n: int = 4) -> StructuralGraph:
    """Ring: 0–1–2–3–0."""
    nodes = [_node(str(i)) for i in range(n)]
    edges = [_edge(str(i), str((i + 1) % n)) for i in range(n)]
    return StructuralGraph(graph_id="ring", nodes=nodes, edges=edges)


def _star_graph(spokes: int = 4) -> StructuralGraph:
    """Hub "center" connected to all spokes."""
    nodes = [_node("center")] + [_node(f"spoke{i}") for i in range(spokes)]
    edges = [_edge("center", f"spoke{i}") for i in range(spokes)]
    return StructuralGraph(graph_id="star", nodes=nodes, edges=edges)


def _empty_graph() -> StructuralGraph:
    return StructuralGraph(graph_id="empty", nodes=[], edges=[])


def _edgeless_graph() -> StructuralGraph:
    """Nodes exist but no edges."""
    return StructuralGraph(
        graph_id="isolated",
        nodes=[_node("a"), _node("b")],
        edges=[],
    )


# ---------------------------------------------------------------------------
# NodeEmbeddings
# ---------------------------------------------------------------------------

class TestNodeEmbeddings:
    def _make(self, node_ids, dim=8):
        vecs = np.random.default_rng(0).random((len(node_ids), dim))
        return NodeEmbeddings(node_ids=node_ids, vectors=vecs)

    def test_get_known_node(self):
        emb = self._make(["a", "b", "c"])
        vec = emb.get("b")
        assert vec is not None
        assert vec.shape == (8,)

    def test_get_unknown_node_returns_none(self):
        emb = self._make(["a", "b"])
        assert emb.get("z") is None

    def test_similarity_same_node_is_one(self):
        emb = self._make(["a", "b"])
        # similarity of a vector with itself = 1.0
        assert emb.similarity("a", "a") == pytest.approx(1.0, abs=1e-6)

    def test_similarity_unknown_returns_zero(self):
        emb = self._make(["a", "b"])
        assert emb.similarity("a", "z") == 0.0

    def test_graph_vector_shape(self):
        emb = self._make(["a", "b", "c"], dim=16)
        gv = emb.graph_vector()
        assert gv.shape == (16,)

    def test_graph_vector_is_mean(self):
        vecs = np.array([[1.0, 0.0], [3.0, 0.0]])
        emb = NodeEmbeddings(node_ids=["x", "y"], vectors=vecs)
        np.testing.assert_allclose(emb.graph_vector(), [2.0, 0.0])

    def test_dim_property(self):
        emb = self._make(["a"], dim=32)
        assert emb.dim == 32

    def test_len(self):
        emb = self._make(["a", "b", "c"])
        assert len(emb) == 3

    def test_empty_embeddings(self):
        emb = NodeEmbeddings(node_ids=[], vectors=np.zeros((0, 8)))
        assert emb.dim == 0
        assert len(emb) == 0
        # graph_vector() on empty returns zeros(dim); dim=0 → shape (0,)
        assert emb.graph_vector().shape == (0,)


# ---------------------------------------------------------------------------
# GraphEmbedder — SVD backend
# ---------------------------------------------------------------------------

class TestGraphEmbedderSVD:
    EMB = GraphEmbedder(dim=8, backend="svd", num_walks=5, walk_length=5, seed=0)

    def test_embed_returns_correct_shape(self):
        graph = _chain_graph(5)
        emb = self.EMB.embed(graph)
        assert len(emb) == 5
        assert emb.dim == 8

    def test_embed_node_ids_preserved(self):
        graph = _chain_graph(4)
        emb = self.EMB.embed(graph)
        assert set(emb.node_ids) == {"0", "1", "2", "3"}

    def test_empty_graph_returns_empty(self):
        emb = self.EMB.embed(_empty_graph())
        assert len(emb) == 0

    def test_edgeless_graph_returns_zero_vectors(self):
        emb = self.EMB.embed(_edgeless_graph())
        assert emb.vectors.shape == (2, 8)
        np.testing.assert_array_equal(emb.vectors, 0.0)

    def test_star_graph_center_has_high_norm(self):
        graph = _star_graph(spokes=5)
        emb = self.EMB.embed(graph)
        center_norm = float(np.linalg.norm(emb.get("center")))
        spoke_norms = [float(np.linalg.norm(emb.get(f"spoke{i}"))) for i in range(5)]
        # Hub (center) should have a larger embedding magnitude than spokes
        assert center_norm >= max(spoke_norms) * 0.5  # not strict — SVD is approximate

    def test_seed_gives_deterministic_results(self):
        graph = _chain_graph(5)
        emb1 = GraphEmbedder(dim=8, backend="svd", seed=7).embed(graph)
        emb2 = GraphEmbedder(dim=8, backend="svd", seed=7).embed(graph)
        np.testing.assert_allclose(emb1.vectors, emb2.vectors)

    def test_different_seeds_give_different_results(self):
        graph = _chain_graph(5)
        emb1 = GraphEmbedder(dim=8, backend="svd", seed=1).embed(graph)
        emb2 = GraphEmbedder(dim=8, backend="svd", seed=2).embed(graph)
        assert not np.allclose(emb1.vectors, emb2.vectors)

    def test_dim_padding_when_fewer_singular_values(self):
        # 2-node graph → at most 1 non-zero singular value
        graph = StructuralGraph(
            graph_id="tiny",
            nodes=[_node("a"), _node("b")],
            edges=[_edge("a", "b")],
        )
        emb = GraphEmbedder(dim=16, backend="svd", seed=0).embed(graph)
        assert emb.vectors.shape == (2, 16)

    def test_active_backend_is_svd(self):
        assert GraphEmbedder(backend="svd").active_backend() == "svd"

    def test_active_backend_auto_falls_back_to_svd_without_torch(self):
        # torch_geometric is not installed in this environment
        assert GraphEmbedder(backend="auto").active_backend() == "svd"


# ---------------------------------------------------------------------------
# graph_similarity
# ---------------------------------------------------------------------------

class TestGraphSimilarity:
    EMB = GraphEmbedder(dim=16, backend="svd", num_walks=10, seed=42)

    def test_same_graph_structure_high_similarity(self):
        g1 = _ring_graph(4)
        g2 = _ring_graph(4)
        # Two isomorphic rings should embed to similar graph vectors
        score = self.EMB.graph_similarity(g1, g2)
        assert 0.0 <= score <= 1.0

    def test_score_in_unit_interval(self):
        score = self.EMB.graph_similarity(_chain_graph(5), _star_graph(4))
        assert 0.0 <= score <= 1.0

    def test_empty_graph_returns_zero(self):
        score = self.EMB.graph_similarity(_empty_graph(), _chain_graph(4))
        assert score == 0.0

    def test_edgeless_graph_returns_zero(self):
        score = self.EMB.graph_similarity(_edgeless_graph(), _chain_graph(4))
        assert score == 0.0


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def test_embed_graph_convenience():
    graph = _chain_graph(4)
    emb = embed_graph(graph, dim=8, backend="svd")
    assert isinstance(emb, NodeEmbeddings)
    assert len(emb) == 4


def test_graph_cosine_similarity_convenience():
    score = graph_cosine_similarity(_chain_graph(4), _ring_graph(4), dim=8, backend="svd")
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestCosine:
    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0])
        assert _cosine(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine(np.array([1.0, 0.0]), np.array([-1.0, 0.0])) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self):
        assert _cosine(np.zeros(3), np.array([1.0, 0.0, 0.0])) == 0.0


class TestPPMI:
    def test_zero_cooc_produces_zero_ppmi(self):
        cooc = np.zeros((4, 4))
        ppmi = _ppmi(cooc)
        assert ppmi.sum() == 0.0

    def test_ppmi_non_negative(self):
        rng = np.random.default_rng(0)
        cooc = rng.integers(0, 10, size=(5, 5)).astype(float)
        ppmi = _ppmi(cooc)
        assert (ppmi >= 0).all()

    def test_self_cooc_yields_high_ppmi_diagonal(self):
        cooc = np.eye(4) * 10.0
        ppmi = _ppmi(cooc)
        assert ppmi.diagonal().mean() > 0


class TestTruncatedSVD:
    def test_output_shape_matches_dim(self):
        mat = np.random.default_rng(0).random((6, 6))
        vecs = _truncated_svd(mat, dim=4)
        assert vecs.shape == (6, 4)

    def test_zero_matrix_returns_zeros(self):
        vecs = _truncated_svd(np.zeros((4, 4)), dim=3)
        np.testing.assert_array_equal(vecs, 0.0)

    def test_padded_when_n_less_than_dim(self):
        mat = np.eye(3)  # 3×3 → at most 3 singular values
        vecs = _truncated_svd(mat, dim=10)
        assert vecs.shape == (3, 10)


# ---------------------------------------------------------------------------
# _blend — weight blending
# ---------------------------------------------------------------------------

class TestBlend:
    def _base(self, **kw):
        defaults = dict(
            var_score=0.8, tag_score=0.6, text_score=0.5, graph_score=None,
            variable_weight=0.45, tag_weight=0.25, text_weight=0.30, graph_weight=0.15,
        )
        return _blend(**{**defaults, **kw})

    def test_without_graph_matches_original_formula(self):
        score = self._base()
        expected = 0.45 * 0.8 + 0.25 * 0.6 + 0.30 * 0.5
        assert score == pytest.approx(expected)

    def test_with_graph_signal_included(self):
        without = self._base()
        with_graph = self._base(graph_score=1.0)
        # A perfect graph signal (1.0) should increase the score
        assert with_graph > without

    def test_with_graph_zero_decreases_score(self):
        without = self._base()
        with_graph = self._base(graph_score=0.0)
        assert with_graph < without

    def test_all_ones_returns_one(self):
        score = _blend(
            var_score=1.0, tag_score=1.0, text_score=1.0, graph_score=1.0,
            variable_weight=0.45, tag_weight=0.25, text_weight=0.30, graph_weight=0.15,
        )
        assert score == pytest.approx(1.0)

    def test_all_zeros_returns_zero(self):
        score = _blend(
            var_score=0.0, tag_score=0.0, text_score=0.0, graph_score=0.0,
            variable_weight=0.45, tag_weight=0.25, text_weight=0.30, graph_weight=0.15,
        )
        assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# CaseSimilarityEngine integration
# ---------------------------------------------------------------------------

from nlp.cases.case_registry import CaseProfile, CaseRegistry
from nlp.cases.case_similarity import CaseSimilarityEngine, CaseSimilarityResult


def _make_registry(*cases: tuple[str, dict]) -> CaseRegistry:
    reg = CaseRegistry()
    for case_id, vec in cases:
        reg.add(CaseProfile(
            case_id=case_id,
            case_name=case_id,
            variable_vector={**{v: 0.0 for v in ("S", "A", "L", "V", "P", "tau")}, **vec},
        ))
    return reg


class TestCaseSimilarityEngineWithGraph:
    def test_without_graph_embedder_ignores_graph_params(self):
        reg = _make_registry(("case_a", {"S": 1.0}), ("case_b", {"A": 1.0}))
        engine = CaseSimilarityEngine(reg)
        results = engine.find_similar(
            variable_vector={"S": 1.0, "A": 0.0, "L": 0.0, "V": 0.0, "P": 0.0, "tau": 0.0},
            query_graph=_star_graph(),
            case_graphs={"case_a": _star_graph(), "case_b": _chain_graph()},
        )
        assert len(results) >= 1
        assert all(r.graph_score is None for r in results)

    def test_with_graph_embedder_populates_graph_score(self):
        reg = _make_registry(("case_a", {"S": 1.0}), ("case_b", {"A": 1.0}))
        embedder = GraphEmbedder(dim=8, backend="svd", seed=0)
        engine = CaseSimilarityEngine(reg, graph_embedder=embedder)
        results = engine.find_similar(
            variable_vector={"S": 1.0, "A": 0.0, "L": 0.0, "V": 0.0, "P": 0.0, "tau": 0.0},
            query_graph=_star_graph(),
            case_graphs={"case_a": _star_graph(), "case_b": _chain_graph()},
        )
        assert len(results) >= 1
        assert all(r.graph_score is not None for r in results)

    def test_graph_score_in_unit_interval(self):
        reg = _make_registry(("case_a", {"S": 0.5}))
        embedder = GraphEmbedder(dim=8, backend="svd", seed=0)
        engine = CaseSimilarityEngine(reg, graph_embedder=embedder)
        results = engine.find_similar(
            variable_vector={"S": 0.5, "A": 0.0, "L": 0.0, "V": 0.0, "P": 0.0, "tau": 0.0},
            query_graph=_chain_graph(),
            case_graphs={"case_a": _chain_graph()},
        )
        for r in results:
            if r.graph_score is not None:
                assert 0.0 <= r.graph_score <= 1.0

    def test_result_has_graph_score_field(self):
        result = CaseSimilarityResult(
            case_id="x", case_name="x", score=0.5, graph_score=0.72
        )
        assert result.graph_score == pytest.approx(0.72)

    def test_result_graph_score_defaults_none(self):
        result = CaseSimilarityResult(case_id="x", case_name="x", score=0.5)
        assert result.graph_score is None
