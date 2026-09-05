from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import numpy as np
import pandas as pd

from src.core.interfaces import ReflexivityDetectorInterface
from src.ml.ml_reflexivity import DTWReflexivityDetector


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except Exception:
        return False


@dataclass
class GraphReflexivityDetector(ReflexivityDetectorInterface):
    """Correlation-graph reflexivity proxy with optional torch refinement."""

    window: int = 60
    channel_threshold: float = 0.6
    density_z_threshold: float = 1.5
    _fallback: DTWReflexivityDetector = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._fallback = DTWReflexivityDetector(channel_threshold=self.channel_threshold)

    def check(self, event_log: pd.DataFrame, proxy_history: pd.DataFrame, run_date: str) -> dict[str, bool]:
        base = cast(dict[str, bool], self._fallback.check(event_log, proxy_history, run_date))
        if proxy_history.empty or len(proxy_history) < max(8, self.window // 4):
            return base

        cols = [c for c in ("M", "D", "K", "X") if c in proxy_history.columns]
        if len(cols) < 2:
            return base

        sub = proxy_history.tail(self.window).copy()
        mat = sub[cols].apply(pd.to_numeric, errors="coerce").dropna()
        if mat.shape[0] < 8:
            return base

        corr = mat.corr().to_numpy(dtype=float)
        np.fill_diagonal(corr, 0.0)
        density = float(np.mean(np.abs(corr)))
        # z-score vs sampling of shuffled rows (cheap null)
        rng = np.random.default_rng(42)
        draws = []
        arr = mat.to_numpy(dtype=float)
        for _ in range(40):
            idx = rng.permutation(arr.shape[0])
            c2 = np.corrcoef(arr[idx].T)
            np.fill_diagonal(c2, 0.0)
            draws.append(float(np.mean(np.abs(c2))))
        mu, sd = float(np.mean(draws)), float(np.std(draws) + 1e-9)
        z = (density - mu) / sd

        graph_flag = z >= self.density_z_threshold
        policy_score = self._fallback._policy_signal(event_log)  # noqa: SLF001

        credit = bool(graph_flag and base["credit"])
        liquidity = bool(graph_flag and base["liquidity"])
        policy = bool(graph_flag or policy_score >= self.channel_threshold)

        if _torch_available():
            # Optional: amplify when average pairwise correlation is extreme
            flat = corr[np.triu_indices_from(corr, k=1)]
            if flat.size and float(np.max(np.abs(flat))) > 0.85:
                credit = credit or bool(base["credit"])
                liquidity = liquidity or bool(base["liquidity"])

        return {"credit": credit, "liquidity": liquidity, "policy": policy}
