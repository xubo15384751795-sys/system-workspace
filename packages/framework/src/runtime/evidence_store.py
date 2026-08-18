from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, cast

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
    canonical_chain: Mapping[str, Any] | None = None


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
        families = {
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
        }
        bundle = EvidenceBundle(
            run_date=snapshot.run_date,
            target_type="snapshot",
            families=families,
            metadata={
                "definition_count": len(self.definitions),
                "source_assets": ["evidence_features", "graph_state_features", "snapshot"],
                "notes": (
                    "Evidence bundles are feature-style summaries for replay, verification, and future serving.",
                    "They are not policy decisions and do not replace Core judgment.",
                ),
            },
            canonical_chain=_canonical_evidence_bundle_chain(snapshot, families),
        )
        self._cache[snapshot.run_date] = bundle
        return bundle


def _canonical_evidence_bundle_chain(
    snapshot: Snapshot,
    families: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Expose the computed evidence bundle as a diagnostic-only canonical chain."""
    try:
        from system_runtime.canonical_ids import (
            build_chain,
            build_claim,
            build_evidence,
            build_measurement,
            build_observation,
        )
    except ImportError:
        return None

    provenance = dict(snapshot.state.provenance or {})
    run_date = str(snapshot.run_date)
    observed_at = run_date if "T" in run_date else f"{run_date}T00:00:00Z"
    quality = str((provenance.get("data_quality") or {}).get("research_quality") or "").lower()
    availability = {
        "mock": "MISSING",
        "degraded": "STALE",
        "clean": "AVAILABLE",
    }.get(quality, "AVAILABLE")
    source_id = str(provenance.get("source_id") or "framework:evidence_store")
    source_snapshot_sha256 = provenance.get("source_snapshot_sha256") or provenance.get("snapshot_sha256")
    captured_at = str(provenance.get("generated_at") or provenance.get("captured_at") or observed_at)
    if "T" not in captured_at:
        captured_at = observed_at
    shared_provenance = {
        "captured_at": captured_at,
        "producer": "framework.runtime.evidence_store",
        "run_id": f"{snapshot.run_date}_{snapshot.run_type}",
        "statement_kind": "diagnostic_evidence_bundle",
        "claim_ceiling": "diagnostic_watch_only",
        "promotion_allowed": False,
    }
    serializable_families = json.loads(json.dumps(families, default=str))
    observation = build_observation(
        canonical_series_id="FRAMEWORK:EVIDENCE_BUNDLE",
        observed_at=observed_at,
        vintage_at=observed_at,
        value=serializable_families,
        unit="derived_evidence_features",
        source_id=source_id,
        status=availability,
        source_snapshot_sha256=source_snapshot_sha256,
        provenance=shared_provenance,
    )
    measurement = build_measurement(
        observation_ids=[observation["observation_id"]],
        measurement_definition="framework_runtime_evidence_bundle",
        value=serializable_families,
        unit="derived_evidence_features",
        status=availability,
        derivation="PROXY_DERIVED",
        method_version="framework.evidence_store.v1",
        provenance=shared_provenance,
    )
    evidence = build_evidence(
        measurement_ids=[measurement["measurement_id"]],
        evidence_role="DERIVED",
        source_id=source_id,
        release_id=provenance.get("source_release_id"),
        source_snapshot_sha256=source_snapshot_sha256,
        status=availability,
        provenance=shared_provenance,
    )
    claim_status = {
        "AVAILABLE": "WATCH",
        "STALE": "STALE",
    }.get(availability, "INSUFFICIENT_DATA")
    claim = build_claim(
        claim_text="Framework runtime evidence bundle is available for bounded diagnostic monitoring.",
        subject="framework_runtime_evidence_bundle",
        predicate="supports_diagnostic_monitoring",
        policy_version="framework.evidence_store.v1",
        evidence_ids=[evidence["evidence_id"]],
        status=claim_status,
        confidence=None,
        provenance=shared_provenance,
    )
    return build_chain(
        observation=observation,
        measurement=measurement,
        evidence=evidence,
        claim=claim,
    )


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
    return cast(float, state_distance(current_state, previous_state))


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
