"""Node2Vec-style graph embeddings over StructuralGraph.

Two execution backends, selected automatically:

``torch``  — PyTorch Geometric ``Node2Vec`` (install ``structural-workbench[gnn]``).
             Full biased random walk with learnable skip-gram objective.
             Best for larger graphs or when embedding quality matters most.

``svd``    — Random-walk co-occurrence + PPMI + truncated SVD (numpy-only, always available).
             Fast and deterministic. Good for small graphs (< 200 nodes) and
             for cases where torch-geometric is not installed.

Usage::

    from nlp.narrative.graph_builder import build_graph_from_event_cards
    from ml.graph_embed import GraphEmbedder

    graph = build_graph_from_event_cards(cards)
    embedder = GraphEmbedder(dim=32)
    embs = embedder.embed(graph)

    # Node-level lookup
    vec = embs.get("federal_reserve")   # np.ndarray | None

    # Graph-level comparison (mean-pooled)
    score = embedder.graph_similarity(graph_2020, graph_2008)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np

if TYPE_CHECKING:
    from nlp.narrative.graph_builder import StructuralGraph


# ---------------------------------------------------------------------------
# NodeEmbeddings — typed result container
# ---------------------------------------------------------------------------

@dataclass
class NodeEmbeddings:
    """Embedding vectors for all nodes in a StructuralGraph.

    Attributes:
        node_ids: Ordered list of node IDs matching ``vectors`` rows.
        vectors:  Float matrix of shape ``(n_nodes, dim)``.
    """

    node_ids: list[str]
    vectors: np.ndarray  # (n_nodes, dim)

    def get(self, node_id: str) -> np.ndarray | None:
        """Return the embedding vector for *node_id*, or ``None`` if absent."""
        try:
            idx = self.node_ids.index(node_id)
        except ValueError:
            return None
        return self.vectors[idx]

    def similarity(self, id_a: str, id_b: str) -> float:
        """Cosine similarity between two nodes in this embedding space."""
        va = self.get(id_a)
        vb = self.get(id_b)
        if va is None or vb is None:
            return 0.0
        return float(_cosine(va, vb))

    def graph_vector(self) -> np.ndarray:
        """Mean-pooled graph-level embedding (shape: ``(dim,)``)."""
        if len(self.vectors) == 0:
            return cast(np.ndarray, np.zeros(self.dim))
        return cast(np.ndarray, self.vectors.mean(axis=0))

    @property
    def dim(self) -> int:
        return int(self.vectors.shape[1]) if self.vectors.ndim == 2 and len(self.vectors) > 0 else 0

    def __len__(self) -> int:
        return len(self.node_ids)

    def __repr__(self) -> str:
        return f"NodeEmbeddings(n={len(self)}, dim={self.dim})"


# ---------------------------------------------------------------------------
# GraphEmbedder
# ---------------------------------------------------------------------------

class GraphEmbedder:
    """Embed a ``StructuralGraph`` into a continuous vector space.

    Parameters
    ----------
    dim:
        Embedding dimensionality.
    walk_length:
        Steps per random walk.
    num_walks:
        Number of walks starting from each node.
    window_size:
        Co-occurrence context window (SVD path) / ``context_size`` (torch path).
    p:
        Node2Vec return parameter (torch path only; ignored in SVD path).
    q:
        Node2Vec in-out parameter (torch path only; ignored in SVD path).
    epochs:
        Training epochs (torch path only).
    backend:
        ``"auto"`` (default) — use torch if available, else SVD.
        ``"torch"``          — require torch-geometric (raises if absent).
        ``"svd"``            — always use the numpy fallback.
    seed:
        Random seed for SVD fallback reproducibility.
    """

    def __init__(
        self,
        dim: int = 64,
        walk_length: int = 10,
        num_walks: int = 20,
        window_size: int = 5,
        p: float = 1.0,
        q: float = 1.0,
        epochs: int = 100,
        backend: str = "auto",
        seed: int = 42,
    ) -> None:
        self.dim = dim
        self.walk_length = walk_length
        self.num_walks = num_walks
        self.window_size = window_size
        self.p = p
        self.q = q
        self.epochs = epochs
        self.backend = backend
        self.seed = seed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, graph: "StructuralGraph") -> NodeEmbeddings:
        """Compute node embeddings for *graph*.

        Returns an empty ``NodeEmbeddings`` (dim=``self.dim``) if the graph
        has no nodes or no edges.
        """
        if not graph.nodes:
            return NodeEmbeddings(node_ids=[], vectors=np.zeros((0, self.dim)))

        node_ids = [n.id for n in graph.nodes]
        n = len(node_ids)
        idx = {nid: i for i, nid in enumerate(node_ids)}

        # Confidence-weighted symmetric adjacency matrix
        adj: np.ndarray = np.zeros((n, n), dtype=float)
        for edge in graph.edges:
            si = idx.get(edge.source)
            ti = idx.get(edge.target)
            if si is not None and ti is not None:
                w = float(edge.confidence)
                adj[si, ti] = max(adj[si, ti], w)
                adj[ti, si] = max(adj[ti, si], w)

        if adj.sum() < 1e-12:
            # No edges — return zero embeddings (structurally uninformative)
            return NodeEmbeddings(node_ids=node_ids, vectors=np.zeros((n, self.dim)))

        if self._use_torch():
            vectors = self._embed_torch(adj, n)
        else:
            vectors = self._embed_svd(adj, n)

        return NodeEmbeddings(node_ids=node_ids, vectors=vectors)

    def graph_similarity(
        self,
        graph_a: "StructuralGraph",
        graph_b: "StructuralGraph",
    ) -> float:
        """Compare two graphs via cosine similarity of their mean-pooled embeddings.

        Returns 0.0 if either graph produces a zero embedding (no edges).
        """
        emb_a = self.embed(graph_a)
        emb_b = self.embed(graph_b)
        if emb_a.dim == 0 or emb_b.dim == 0:
            return 0.0
        va = emb_a.graph_vector()
        vb = emb_b.graph_vector()
        return float(max(0.0, _cosine(va, vb)))

    def active_backend(self) -> str:
        """Return the backend that will actually be used: ``"torch"`` or ``"svd"``."""
        return "torch" if self._use_torch() else "svd"

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    def _use_torch(self) -> bool:
        if self.backend == "svd":
            return False
        if self.backend == "torch":
            _require_torch()
            return True
        # auto — silent fallback
        try:
            import torch  # noqa: F401
            import torch_geometric  # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Torch-Geometric backend
    # ------------------------------------------------------------------

    def _embed_torch(self, adj: np.ndarray, n: int) -> np.ndarray:
        import torch
        from torch_geometric.nn import Node2Vec as _Node2Vec

        edges = np.argwhere(adj > 0)
        if len(edges) == 0:
            return cast(np.ndarray, np.zeros((n, self.dim)))

        edge_index = torch.tensor(edges.T, dtype=torch.long)
        context = min(self.window_size, self.walk_length)

        model = _Node2Vec(
            edge_index,
            embedding_dim=self.dim,
            walk_length=self.walk_length,
            context_size=context,
            walks_per_node=self.num_walks,
            p=self.p,
            q=self.q,
            num_negative_samples=1,
            num_nodes=n,
            sparse=True,
        )

        optimizer = torch.optim.SparseAdam(list(model.parameters()), lr=0.01)
        loader = model.loader(
            batch_size=min(128, max(1, n * self.num_walks)),
            shuffle=True,
            num_workers=0,
        )

        model.train()
        for _ in range(self.epochs):
            for pos_rw, neg_rw in loader:
                optimizer.zero_grad()
                loss = model.loss(pos_rw, neg_rw)
                loss.backward()
                optimizer.step()

        return cast(np.ndarray, model().detach().cpu().numpy())

    # ------------------------------------------------------------------
    # SVD fallback (numpy-only)
    # ------------------------------------------------------------------

    def _embed_svd(self, adj: np.ndarray, n: int) -> np.ndarray:
        rng = np.random.default_rng(self.seed)

        # Row-normalised transition matrix
        row_sum = adj.sum(axis=1, keepdims=True)
        trans = np.where(row_sum > 1e-12, adj / row_sum, 0.0)

        # Random walks → co-occurrence matrix
        cooc: np.ndarray = np.zeros((n, n), dtype=float)
        for start in range(n):
            for _ in range(self.num_walks):
                walk = _random_walk(start, n, trans, self.walk_length, rng)
                _accumulate_cooc(cooc, walk, self.window_size)

        # PPMI transformation
        ppmi = _ppmi(cooc)

        # Truncated SVD
        return _truncated_svd(ppmi, self.dim)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def embed_graph(
    graph: "StructuralGraph",
    *,
    dim: int = 64,
    backend: str = "auto",
    seed: int = 42,
) -> NodeEmbeddings:
    """One-shot helper: embed *graph* with default settings."""
    return GraphEmbedder(dim=dim, backend=backend, seed=seed).embed(graph)


def graph_cosine_similarity(
    graph_a: "StructuralGraph",
    graph_b: "StructuralGraph",
    *,
    dim: int = 64,
    backend: str = "auto",
) -> float:
    """Compare two graphs by cosine similarity of their mean-pooled embeddings."""
    return GraphEmbedder(dim=dim, backend=backend).graph_similarity(graph_a, graph_b)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
    return float(np.clip(np.dot(a, b) / (norm_a * norm_b), -1.0, 1.0))


def _random_walk(
    start: int,
    n: int,
    trans: np.ndarray,
    walk_length: int,
    rng: np.random.Generator,
) -> list[int]:
    walk = [start]
    for _ in range(walk_length - 1):
        curr = walk[-1]
        probs = trans[curr]
        total = probs.sum()
        if total < 1e-12:
            break
        walk.append(int(rng.choice(n, p=probs / total)))
    return walk


def _accumulate_cooc(cooc: np.ndarray, walk: list[int], window: int) -> None:
    length = len(walk)
    for i, u in enumerate(walk):
        lo = max(0, i - window)
        hi = min(length, i + window + 1)
        for j in range(lo, hi):
            if i != j:
                cooc[u, walk[j]] += 1.0


def _ppmi(cooc: np.ndarray) -> np.ndarray:
    total = cooc.sum() + 1e-12
    row_s = cooc.sum(axis=1, keepdims=True) + 1e-12
    col_s = cooc.sum(axis=0, keepdims=True) + 1e-12
    with np.errstate(divide="ignore", invalid="ignore"):
        pmi = np.log((cooc * total) / (row_s * col_s))
    pmi = np.nan_to_num(pmi, nan=0.0, posinf=0.0, neginf=0.0)
    return cast(np.ndarray, np.maximum(pmi, 0.0))


def _truncated_svd(matrix: np.ndarray, dim: int) -> np.ndarray:
    n = matrix.shape[0]
    if matrix.sum() < 1e-12 or n < 2:
        return cast(np.ndarray, np.zeros((n, dim)))
    try:
        U, S, _ = np.linalg.svd(matrix, full_matrices=False)
        k = min(dim, len(S))
        vectors = U[:, :k] * S[:k]
    except np.linalg.LinAlgError:
        return cast(np.ndarray, np.zeros((n, dim)))
    # Pad to `dim` if fewer singular values than requested
    if vectors.shape[1] < dim:
        pad = np.zeros((n, dim - vectors.shape[1]))
        vectors = np.concatenate([vectors, pad], axis=1)
    return cast(np.ndarray, vectors)


def _require_torch() -> None:
    try:
        import torch  # noqa: F401
        import torch_geometric  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "torch backend requires PyTorch and PyTorch Geometric.\n"
            "Install with:  pip install 'structural-workbench[gnn]'"
        ) from exc
