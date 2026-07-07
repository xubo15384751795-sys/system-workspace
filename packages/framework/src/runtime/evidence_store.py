from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from src.core.metrics.distance import state_distance
from src.core.metrics.graph_features import graph_feature_evidence
from src.core.metrics.persistence import multi_window_stability
from src.core.models import Snapshot
from src.core.representation.graph_repr import StructuralEdge, build_graph


@dataclass(frozen=True)
class EvidenceDefinition:
    family: str
    target: str
    description: str
    version: str = "v1"
    source_assets: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceBundle:
    run_date: str
    target_type: str
    families: Mapping[str, Mapping[str, Any]]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeEvidenceStore:
    definitions: tuple[EvidenceDefinition, ...] = field(default_factory=lambda: default_evidence_definitions())
    _cache: dict[str, EvidenceBundle] = field(default_factory=dict)

    def list_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "family": item.family,
                "target": item.target,
                "description": item.description,
                "version": item.version,
                "source_assets": list(item.source_assets),
            }
            for item in self.definitions
        ]

    def build_snapshot_bundle(
        self,
        snapshot: Snapshot,
        history: Sequence[Snapshot] | None = None,
        refresh: bool = False,
    ) -> EvidenceBundle:
        if not refresh and snapshot.run_date in self._cache:
            return self._cache[snapshot.run_date]

        state_history = list(history or [])
        graph = _snapshot_graph(snapshot)
        graph_evidence = graph_feature_evidence(graph)
        previous = state_history[-1] if state_history else None
        distance_features = {
            "distance_to_previous_state": _distance_to_previous(snapshot, previous),
            "distance_target": "z_vector_or_proxy_state",
        }
        persistence = multi_window_stability(_history_windows(state_history + [snapshot]))
        bundle = EvidenceBundle(
            run_date=snapshot.run_date,
            target_type="snapshot",
            families={
                "graph_features": {
                    "node_count": graph_evidence.node_count,
                    "edge_count": graph_evidence.edge_count,
                    "degree_concentration": graph_evidence.degree_concentration,
                    "fragmentation_proxy": graph_evidence.fragmentation_proxy,
                    "bottleneck_proxy": graph_evidence.bottleneck_proxy,
                    "connectedness_ratio": graph_evidence.connectedness_ratio,
                },
                "distance_features": distance_features,
                "persistence_features": {
                    "stability_score": persistence.stability_score,
                    "mean_distance": persistence.mean_distance,
                    "max_distance": persistence.max_distance,
                    "change_point_count": persistence.change_point_count,
                },
                "state_features": {
                    "sigma_t": snapshot.state.sigma_t,
                    "anomaly_score": snapshot.state.anomaly_score,
                    "singular_flag": snapshot.state.singular_flag,
                },
                "shadow_maturity_features": _shadow_maturity_features(snapshot),
                "mean_field_gap_features": _mean_field_gap_features(snapshot),
            },
            metadata={
                "definition_count": len(self.definitions),
                "source_assets": ["evidence_features", "graph_state_features", "snapshot"],
                "notes": (
                    "Evidence bundles are feature-style summaries for replay, verification, and future serving.",
                    "They are not policy decisions and do not replace Core judgment.",
                ),
            },
        )
        self._cache[snapshot.run_date] = bundle
        return bundle


def default_evidence_definitions() -> tuple[EvidenceDefinition, ...]:
    return (
        EvidenceDefinition(
            family="graph_features",
            target="snapshot",
            description="Graph-derived structural evidence for current candidate relationships.",
            source_assets=("graph_state_features",),
        ),
        EvidenceDefinition(
            family="distance_features",
            target="snapshot",
            description="Distance-style deltas between structural states across runs.",
            source_assets=("snapshot", "observation_pool"),
        ),
        EvidenceDefinition(
            family="persistence_features",
            target="snapshot",
            description="Multi-window stability and change-point evidence across history.",
            source_assets=("observation_pool", "evidence_features"),
        ),
        EvidenceDefinition(
            family="state_features",
            target="snapshot",
            description="Direct state-level evidence such as sigma and anomaly score.",
            source_assets=("snapshot",),
        ),
        EvidenceDefinition(
            family="shadow_maturity_features",
            target="snapshot",
            description="Shadow mass profile across realization horizons and forced-release pressure.",
            source_assets=("snapshot", "evidence_features"),
        ),
        EvidenceDefinition(
            family="mean_field_gap_features",
            target="snapshot",
            description="Gap between coupled shadow load and decoupled representative benchmark.",
            source_assets=("snapshot", "evidence_features"),
        ),
    )


def _snapshot_graph(snapshot: Snapshot):
    proxy_state = {
        "M": snapshot.proxy.M or 0.0,
        "D": snapshot.proxy.D or 0.0,
        "K": snapshot.proxy.K or 0.0,
        "X": snapshot.proxy.X or 0.0,
    }
    channels = list(proxy_state.items())
    edges: list[StructuralEdge] = []
    for idx, (left_name, left_value) in enumerate(channels):
        for right_name, right_value in channels[idx + 1 :]:
            activation = (abs(left_value) + abs(right_value)) / 2.0
            similarity = 1.0 / (1.0 + abs(left_value - right_value))
            if activation < 0.1 and similarity < 0.6:
                continue
            edges.append(
                StructuralEdge(
                    source=left_name,
                    target=right_name,
                    weight=float(similarity * max(activation, 0.1)),
                    edge_type="state_affinity",
                    metadata={
                        "activation": float(activation),
                        "similarity": float(similarity),
                    },
                )
            )
    return build_graph(proxy_state, edges=edges)


def _history_windows(history: Sequence[Snapshot]) -> list[list[np.ndarray | Mapping[str, float]]]:
    windows: list[list[np.ndarray | Mapping[str, float]]] = []
    for snapshot in history:
        if snapshot.state.z_vector is not None:
            windows.append([np.asarray(snapshot.state.z_vector, dtype=float)])
        else:
            windows.append(
                [
                    {
                        "M": snapshot.proxy.M or 0.0,
                        "D": snapshot.proxy.D or 0.0,
                        "K": snapshot.proxy.K or 0.0,
                        "X": snapshot.proxy.X or 0.0,
                    }
                ]
            )
    return windows


def _distance_to_previous(current: Snapshot, previous: Snapshot | None) -> float:
    if previous is None:
        return 0.0
    current_state = current.state.z_vector if current.state.z_vector is not None else _proxy_state(current)
    previous_state = previous.state.z_vector if previous.state.z_vector is not None else _proxy_state(previous)
    return state_distance(current_state, previous_state)


def _proxy_state(snapshot: Snapshot) -> dict[str, float]:
    return {
        "M": snapshot.proxy.M or 0.0,
        "D": snapshot.proxy.D or 0.0,
        "K": snapshot.proxy.K or 0.0,
        "X": snapshot.proxy.X or 0.0,
    }


def _shadow_maturity_features(snapshot: Snapshot) -> dict[str, Any]:
    shadow = snapshot.state.shadow_mass_state
    if shadow is None:
        return {
            "aggregate_mass": None,
            "forced_realization_pressure": None,
            "bucket_count": 0,
            "bucket_masses": {},
        }
    return {
        "aggregate_mass": shadow.aggregate_mass,
        "forced_realization_pressure": shadow.forced_realization_pressure,
        "bucket_count": len(shadow.buckets),
        "bucket_masses": {bucket.name: bucket.mass for bucket in shadow.buckets},
        "bucket_intensities": {bucket.name: bucket.realization_intensity for bucket in shadow.buckets},
    }


def _mean_field_gap_features(snapshot: Snapshot) -> dict[str, Any]:
    gap = snapshot.state.mean_field_gap
    if gap is None:
        return {
            "actual_shadow_mass": None,
            "benchmark_shadow_mass": None,
            "gap": None,
            "normalized_gap": None,
        }
    return {
        "actual_shadow_mass": gap.actual_shadow_mass,
        "benchmark_shadow_mass": gap.benchmark_shadow_mass,
        "gap": gap.gap,
        "normalized_gap": gap.normalized_gap,
    }
