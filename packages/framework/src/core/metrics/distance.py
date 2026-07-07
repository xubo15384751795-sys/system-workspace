from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np


def state_distance(
    left: np.ndarray | Mapping[str, float],
    right: np.ndarray | Mapping[str, float],
    metric: str = "euclidean",
) -> float:
    a = _coerce_vector(left)
    b = _coerce_vector(right)
    delta = a - b
    if metric == "euclidean":
        return float(np.linalg.norm(delta))
    if metric == "manhattan":
        return float(np.abs(delta).sum())
    if metric == "chebyshev":
        return float(np.abs(delta).max())
    if metric == "cosine":
        return _cosine_distance(a, b)
    raise ValueError(f"Unsupported state distance metric: {metric}")


def pairwise_state_distance_matrix(
    states: Sequence[np.ndarray | Mapping[str, float]],
    metric: str = "euclidean",
) -> np.ndarray:
    vectors = np.vstack([_coerce_vector(state) for state in states]) if states else np.zeros((0, 0), dtype=float)
    if vectors.size == 0:
        return np.zeros((0, 0), dtype=float)
    try:
        from sklearn.metrics import pairwise_distances  # type: ignore

        return np.asarray(pairwise_distances(vectors, metric=metric), dtype=float)
    except Exception:
        return _pairwise_fallback(vectors, metric=metric)


def _coerce_vector(value: np.ndarray | Mapping[str, float]) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return np.asarray(value, dtype=float)
    ordered = [float(value.get(channel, 0.0)) for channel in sorted(value.keys())]
    return np.asarray(ordered, dtype=float)


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(1.0 - (np.dot(a, b) / denom))


def _pairwise_fallback(vectors: np.ndarray, metric: str) -> np.ndarray:
    out = np.zeros((vectors.shape[0], vectors.shape[0]), dtype=float)
    for i in range(vectors.shape[0]):
        for j in range(vectors.shape[0]):
            out[i, j] = state_distance(vectors[i], vectors[j], metric=metric)
    return out
