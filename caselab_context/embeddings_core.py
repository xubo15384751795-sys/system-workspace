"""Lightweight TF-IDF embeddings for Paper note retrieval."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

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


def save_embeddings(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_embeddings(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def search(payload: dict[str, Any], query: str, top_k: int = 5) -> list[dict[str, Any]]:
    query_vec = build_tfidf([{"text": query}])["vectors"][0]
    scored: list[tuple[float, dict[str, Any]]] = []
    for doc, vec in zip(payload["docs"], payload["vectors"], strict=False):
        score = cosine_sparse(query_vec, vec)
        if score <= 0:
            continue
        scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"score": round(score, 4), **doc}
        for score, doc in scored[:top_k]
    ]
