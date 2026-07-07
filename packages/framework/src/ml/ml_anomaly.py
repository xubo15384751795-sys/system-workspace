from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.core.interfaces import AnomalyDetectorInterface, SnapshotStoreInterface
from src.core.models import ProxyReading, Snapshot


def _proxy_to_vec(proxy: ProxyReading) -> np.ndarray:
    return np.array(
        [
            float(proxy.M) if proxy.M is not None else 0.0,
            float(proxy.D) if proxy.D is not None else 0.0,
            float(proxy.K) if proxy.K is not None else 0.0,
            float(proxy.X) if proxy.X is not None else 0.0,
        ],
        dtype=np.float64,
    )


def _snapshots_to_matrix(snapshots: list[Snapshot]) -> np.ndarray:
    if not snapshots:
        return np.zeros((0, 4), dtype=np.float64)
    return np.stack([_proxy_to_vec(s.proxy) for s in snapshots], axis=0)


@dataclass
class IsolationForestDetector(AnomalyDetectorInterface):
    """Stateful isolation-forest baseline over historical proxy rows (M/D/K/X).

    Fit once from ``SnapshotStoreInterface.load_range``; score with ``predict``
    semantics where **higher** means more anomalous.
    """

    contamination: float = 0.05
    random_state: int = 7
    min_samples: int = 10
    _model: Any = field(default=None, init=False, repr=False)
    _fitted: bool = field(default=False, init=False, repr=False)

    def fit_from_history(
        self,
        snapshot_store: SnapshotStoreInterface,
        start: str,
        end: str,
    ) -> None:
        snapshots = snapshot_store.load_range(start, end)
        x = _snapshots_to_matrix(snapshots)
        if x.shape[0] < self.min_samples:
            self._model = None
            self._fitted = False
            return
        try:
            from sklearn.ensemble import IsolationForest  # type: ignore

            model = IsolationForest(
                contamination=float(self.contamination),
                random_state=int(self.random_state),
            )
            model.fit(x)
            self._model = model
            self._fitted = True
        except Exception:
            self._model = None
            self._fitted = False

    def score(self, proxy: ProxyReading) -> float:
        vec = _proxy_to_vec(proxy).reshape(1, -1)
        if self._fitted and self._model is not None:
            try:
                # sklearn: lower score_samples => more outlier-like; invert so higher => more anomaly
                return float(-self._model.score_samples(vec)[0])
            except Exception:
                pass
        return self._heuristic_score(proxy)

    def _heuristic_score(self, proxy: ProxyReading) -> float:
        values = _proxy_to_vec(proxy)
        return float(np.mean(np.abs(values)))
