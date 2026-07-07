"""
Stub implementations for testing — no external dependencies.

Each implements the protocol expected by a pipeline component.
These stubs exist so integration tests can wire a full pipeline
without real data sources, ML models, or ODE backends.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.core.models import NarrativeReading, ProxyReading, Snapshot, StructuralBeliefState


@dataclass
class StubProxyBuilder:
    def build(self, raw: pd.DataFrame, run_date: str) -> ProxyReading:
        row = raw.loc[: pd.to_datetime(run_date)].tail(1)
        values: dict[str, float | None] = {"M": None, "D": None, "K": None, "X": None}
        if not row.empty:
            for key, col in zip(values.keys(), raw.columns[:4]):
                value = row.iloc[0][col]
                values[key] = float(value) if pd.notna(value) else None
        directions = {key: "WORSENING" if (val is not None and val > 0.5) else "STABLE" for key, val in values.items()}
        available = {key: val is not None for key, val in values.items()}
        return ProxyReading(
            run_date=run_date,
            M=values["M"],
            D=values["D"],
            K=values["K"],
            X=values["X"],
            directions=directions,
            available=available,
            components=values,
        )


@dataclass
class StubODEEngine:
    def integrate(self, proxy: ProxyReading, params: dict) -> np.ndarray:
        return self.map_proxy_to_initial_state(proxy)

    def map_proxy_to_initial_state(self, proxy: ProxyReading) -> np.ndarray:
        m = proxy.M or 0.0
        d = proxy.D or 0.0
        k = proxy.K or 0.0
        x = proxy.X or 0.0
        return np.array([m, d, k, x, (m + d) / 2.0, (k + x) / 2.0], dtype=float)


@dataclass
class StubSingularDetector:
    threshold: float = 2.0

    def detect(
        self,
        proxy: ProxyReading,
        z: np.ndarray,
        belief_state: StructuralBeliefState | None = None,
    ) -> tuple[float, bool]:
        sigma_t = float(np.linalg.norm(z))
        return sigma_t, sigma_t >= self.threshold


@dataclass
class StubAnomalyDetector:
    def score(self, proxy: ProxyReading) -> float:
        vals = [v for v in [proxy.M, proxy.D, proxy.K, proxy.X] if v is not None]
        if not vals:
            return 0.0
        return float(-np.mean(np.abs(vals)))


@dataclass
class StubNarrativeDetector:
    def analyze(self, texts: list[dict], run_date: str) -> NarrativeReading:
        return NarrativeReading(
            run_date=run_date,
            ai_unicorn="ANCHORED",
            clo_cmbs="ANCHORED",
            policy="ANCHORED",
            drift_scores={"ai_unicorn": 0.0, "clo_cmbs": 0.0, "policy": 0.0},
        )


@dataclass
class StubReflexivityDetector:
    def check(self, event_log: pd.DataFrame, proxy_history: pd.DataFrame, run_date: str) -> dict[str, bool]:
        return {"credit": False, "liquidity": False, "policy": False}


@dataclass
class InMemorySnapshotStore:
    _store: dict[str, Snapshot] = field(default_factory=dict)

    def save(self, snapshot: Snapshot) -> None:
        self._store[snapshot.run_date] = snapshot

    def load(self, run_date: str) -> Snapshot | None:
        return self._store.get(run_date)

    def load_range(self, start: str, end: str) -> list[Snapshot]:
        start_ts = pd.to_datetime(start)
        end_ts = pd.to_datetime(end)
        result = []
        for key in sorted(self._store.keys()):
            ts = pd.to_datetime(key)
            if start_ts <= ts <= end_ts:
                result.append(self._store[key])
        return result

    def iter_range(self, start: str, end: str, batch_size: int = 500) -> Iterator[Snapshot]:
        _ = batch_size
        yield from self.load_range(start, end)

    def load_latest_before(self, run_date: str) -> Snapshot | None:
        run_ts = pd.to_datetime(run_date)
        prior = [
            snapshot
            for key, snapshot in sorted(self._store.items())
            if pd.to_datetime(key) < run_ts
        ]
        return prior[-1] if prior else None
