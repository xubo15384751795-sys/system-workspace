from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from src.core.metrics.distance import state_distance


@dataclass(frozen=True)
class PersistenceEvidence:
    window_count: int
    pairwise_distances: tuple[float, ...]
    mean_distance: float
    max_distance: float
    stability_score: float
    change_point_count: int = 0
    change_points: tuple[int, ...] = ()
    notes: tuple[str, ...] = ()


def multi_window_stability(windows: Sequence[Sequence[np.ndarray | Mapping[str, float]]]) -> PersistenceEvidence:
    representatives = [_window_representative(window) for window in windows if window]
    change_points = detect_structural_change_points(representatives)
    if len(representatives) < 2:
        return PersistenceEvidence(
            window_count=len(representatives),
            pairwise_distances=(),
            mean_distance=0.0,
            max_distance=0.0,
            stability_score=1.0,
            change_point_count=len(change_points),
            change_points=change_points,
            notes=(
                "Too few windows for persistence comparison.",
                "TODO: extend persistence evidence to rolling topology summaries when TDA is activated.",
            ),
        )

    distances = tuple(
        state_distance(representatives[idx], representatives[idx + 1])
        for idx in range(len(representatives) - 1)
    )
    mean_distance = float(np.mean(distances)) if distances else 0.0
    max_distance = float(np.max(distances)) if distances else 0.0
    return PersistenceEvidence(
        window_count=len(representatives),
        pairwise_distances=distances,
        mean_distance=mean_distance,
        max_distance=max_distance,
        stability_score=float(1.0 / (1.0 + mean_distance)),
        change_point_count=len(change_points),
        change_points=change_points,
        notes=(
            "Persistence evidence is descriptive, not adjudicative.",
            "TODO: add persistence-of-graph-state once temporal graph builders are stable.",
        ),
    )


def detect_structural_change_points(
    states: Sequence[np.ndarray | Mapping[str, float]],
    penalty: float = 3.0,
    model: str = "l2",
) -> tuple[int, ...]:
    vectors = [_coerce_vector(state) for state in states]
    if len(vectors) < 3:
        return ()
    signal = np.vstack(vectors)
    try:
        import ruptures as rpt  # type: ignore

        algo = rpt.Pelt(model=model).fit(signal)
        predicted = [int(idx) for idx in algo.predict(pen=float(penalty)) if int(idx) < len(signal)]
        return tuple(predicted)
    except Exception:
        jumps = np.linalg.norm(np.diff(signal, axis=0), axis=1)
        if jumps.size == 0:
            return ()
        threshold = float(np.mean(jumps) + np.std(jumps))
        return tuple(int(idx + 1) for idx, jump in enumerate(jumps) if float(jump) > threshold)


def _window_representative(window: Sequence[np.ndarray | Mapping[str, float]]) -> np.ndarray:
    vectors = [_coerce_vector(state) for state in window]
    return np.mean(np.vstack(vectors), axis=0)


def _coerce_vector(value: np.ndarray | Mapping[str, float]) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return np.asarray(value, dtype=float)
    ordered = [float(value.get(channel, 0.0)) for channel in sorted(value.keys())]
    return np.asarray(ordered, dtype=float)
