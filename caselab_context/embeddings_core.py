"""Sparse and dense embeddings for Paper note retrieval."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from caselab_context.embed_provider import DEFAULT_EMBED_MODEL, default_embed_fn
from caselab_context.graph_core import build_graph

TOKEN_RE = re.compile(r"[a-z0-9_]{2,}")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def build_tfidf(docs: list[dict[str, Any]]) -> dict[str, Any]:
    df: Counter[str] = Counter()
    tokenized: list[list[str]] = []
    for doc in docs:
        tokens = tokenize(doc.get("text", ""))
        tokenized.append(tokens)
        df.update(set(tokens))
    n_docs = max(len(docs), 1)
    vectors: list[dict[str, float]] = []
    for tokens in tokenized:
        tf = Counter(tokens)
        total = sum(tf.values()) or 1
        vec: dict[str, float] = {}
        for token, count in tf.items():
            idf = math.log((1 + n_docs) / (1 + df[token])) + 1.0
            vec[token] = (count / total) * idf
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({k: v / norm for k, v in vec.items()})
    return {"docs": docs, "vectors": vectors}


def cosine_sparse(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(weight * b.get(token, 0.0) for token, weight in a.items())


def cosine_dense(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _sparse_query_vector(query: str) -> dict[str, float]:
    return build_tfidf([{"text": query}])["vectors"][0]


def _score_sparse(payload: dict[str, Any], query: str) -> list[float]:
    sparse_vectors = payload.get("sparse_vectors") or payload.get("vectors") or []
    query_vec = _sparse_query_vector(query)
    return [cosine_sparse(query_vec, vec) for vec in sparse_vectors]


def _score_dense(payload: dict[str, Any], query: str, embed_fn: Callable[[list[str]], list[list[float]]] | None) -> list[float] | None:
    dense_vectors = payload.get("dense_vectors")
    if not dense_vectors:
        return None
    if embed_fn is None:
        return None
    query_vec = embed_fn([query])[0]
    return [cosine_dense(query_vec, vec) for vec in dense_vectors]


def _merge_scores(
    sparse_scores: list[float],
    dense_scores: list[float] | None,
    *,
    dense_weight: float = 0.6,
) -> list[float]:
    if dense_scores is None:
        return sparse_scores
    sparse_weight = 1.0 - dense_weight
    merged: list[float] = []
    for sparse, dense in zip(sparse_scores, dense_scores, strict=False):
        merged.append((sparse_weight * sparse) + (dense_weight * dense))
    return merged


def build_embeddings(
    docs: list[dict[str, Any]],
    *,
    backend: str = "auto",
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> dict[str, Any]:
    sparse_payload = build_tfidf(docs)
    graph = build_graph(docs)
    resolved_backend = backend
    dense_vectors: list[list[float]] | None = None
    embed_model: str | None = None

    if backend in {"auto", "hybrid", "dense"}:
        provider = embed_fn or default_embed_fn()
        if provider is not None:
            try:
                dense_vectors = provider([doc.get("text", "") for doc in docs])
                embed_model = DEFAULT_EMBED_MODEL
            except (OSError, RuntimeError, ValueError, TimeoutError):
                dense_vectors = None

    if dense_vectors and backend == "dense":
        resolved_backend = "dense"
    elif dense_vectors and backend in {"auto", "hybrid"}:
        resolved_backend = "hybrid"
    else:
        resolved_backend = "tfidf"
        dense_vectors = None

    payload: dict[str, Any] = {
        "backend": resolved_backend,
        "embed_model": embed_model,
        "docs": docs,
        "sparse_vectors": sparse_payload["vectors"],
        "vectors": sparse_payload["vectors"],
        "graph": graph,
    }
    if dense_vectors is not None:
        payload["dense_vectors"] = dense_vectors
    return payload


def save_embeddings(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # Mirror into LanceDB when available (ANN store); JSON remains compatibility export.
    try:
        from caselab_context.lancedb_store import lancedb_dir, migrate_payload_to_lancedb

        root = path.resolve().parents[1] if path.name == "embeddings.json" else path.parent
        # Data/caselab_context/embeddings.json -> parents[1] is Data/; use workspace root.
        workspace = path.resolve().parents[2] if "caselab_context" in path.parts else path.parent
        migrate_payload_to_lancedb(payload, db_path=lancedb_dir(workspace))
    except Exception:
        pass


def load_embeddings(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def search(
    payload: dict[str, Any],
    query: str,
    top_k: int = 5,
    *,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[dict[str, Any]]:
    docs = payload.get("docs") or []
    backend = payload.get("backend", "tfidf")

    # Prefer LanceDB ANN when dense vectors / query embedding are available.
    if backend in {"hybrid", "dense"} and payload.get("dense_vectors"):
        provider = embed_fn or default_embed_fn()
        if provider is not None:
            try:
                from caselab_context.lancedb_store import lancedb_dir, search_lancedb

                workspace = Path(__file__).resolve().parents[1]
                query_vec = provider([query])[0]
                lance_hits = search_lancedb(query_vec, db_path=lancedb_dir(workspace), top_k=top_k)
                if lance_hits:
                    return lance_hits
            except Exception:
                pass

    sparse_scores = _score_sparse(payload, query)
    dense_scores = None
    if backend in {"hybrid", "dense"} and payload.get("dense_vectors"):
        dense_scores = _score_dense(payload, query, embed_fn or default_embed_fn())
        if dense_scores is None and backend == "dense":
            dense_scores = [0.0] * len(docs)

    if backend == "dense" and dense_scores is not None:
        final_scores = dense_scores
    elif backend == "hybrid" and dense_scores is not None:
        final_scores = _merge_scores(sparse_scores, dense_scores)
    else:
        final_scores = sparse_scores

    scored: list[tuple[float, dict[str, Any]]] = []
    for doc, score in zip(docs, final_scores, strict=False):
        if score <= 0:
            continue
        scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"score": round(score, 4), **doc}
        for score, doc in scored[:top_k]
    ]
