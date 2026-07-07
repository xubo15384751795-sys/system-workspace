from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np

from src.core.metrics.distance import state_distance
from src.core.representation.graph_repr import (
    StructuralGraph,
    connected_components,
    degree_summary,
    to_networkx,
)


@dataclass(frozen=True)
class GraphFeatureEvidence:
    node_count: int
    edge_count: int
    density: float
    weighted_degree: dict[str, float]
    mean_weighted_degree: float
    max_weighted_degree: float
    degree_concentration: float
    mean_abs_weight: float
    signed_weight_balance: float
    component_count: int
    connectedness_ratio: float
    fragmentation_proxy: float
    bottleneck_proxy: float
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceContribution:
    source: str
    score: float
    redundancy_tag: str | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class EvidenceAccumulation:
    raw_total: float
    adjusted_total: float
    saturation_score: float
    redundancy_penalty: float
    contribution_count: int
    notes: tuple[str, ...]


@dataclass(frozen=True)
class VerificationEvidenceExample:
    graph: GraphFeatureEvidence
    persistence_score: float
    distance_from_reference: float


@dataclass(frozen=True)
class AdjudicationEvidenceExample:
    saturation_score: float
    adjusted_total: float
    inputs: tuple[str, ...]


def graph_feature_evidence(graph: StructuralGraph) -> GraphFeatureEvidence:
    node_count = len(graph.nodes)
    edge_count = len(graph.edges)
    density = float(edge_count / (node_count * (node_count - 1))) if node_count > 1 else 0.0
    weighted_degree = degree_summary(graph)
    degree_values = np.asarray(list(weighted_degree.values()), dtype=float) if weighted_degree else np.asarray([], dtype=float)
    components = connected_components(graph)
    component_count = len(components)
    connectedness_ratio = _connectedness_ratio(node_count=node_count, component_count=component_count)
    fragmentation_proxy = 1.0 - connectedness_ratio
    bottleneck_proxy = _bottleneck_proxy(degree_values, graph)

    if not graph.edges:
        return GraphFeatureEvidence(
            node_count=node_count,
            edge_count=edge_count,
            density=density,
            weighted_degree=weighted_degree,
            mean_weighted_degree=0.0,
            max_weighted_degree=0.0,
            degree_concentration=0.0,
            mean_abs_weight=0.0,
            signed_weight_balance=0.0,
            component_count=component_count,
            connectedness_ratio=connectedness_ratio,
            fragmentation_proxy=fragmentation_proxy,
            bottleneck_proxy=bottleneck_proxy,
            notes=(
                "No structural edges were present; graph evidence is node-only.",
                "TODO: add temporal edge semantics before interpreting edge absence as true fragmentation.",
            ),
        )

    weights = np.asarray([edge.weight for edge in graph.edges], dtype=float)
    return GraphFeatureEvidence(
        node_count=node_count,
        edge_count=edge_count,
        density=density,
        weighted_degree=weighted_degree,
        mean_weighted_degree=float(np.mean(degree_values)) if degree_values.size else 0.0,
        max_weighted_degree=float(np.max(degree_values)) if degree_values.size else 0.0,
        degree_concentration=_degree_concentration(degree_values),
        mean_abs_weight=float(np.mean(np.abs(weights))),
        signed_weight_balance=float(np.sum(np.sign(weights)) / len(weights)),
        component_count=component_count,
        connectedness_ratio=connectedness_ratio,
        fragmentation_proxy=fragmentation_proxy,
        bottleneck_proxy=bottleneck_proxy,
        notes=(
            "Graph features are evidence summaries, not policy decisions.",
            "TODO: replace bottleneck proxy with path-sensitive flow constraints when graph semantics mature.",
        ),
    )


def accumulate_evidence(
    contributions: Iterable[EvidenceContribution],
    saturation_scale: float = 1.0,
    redundancy_discount: float = 0.15,
) -> EvidenceAccumulation:
    items = list(contributions)
    raw_total = float(sum(max(0.0, item.score) for item in items))
    tag_counts: dict[str, int] = {}
    for item in items:
        if not item.redundancy_tag:
            continue
        tag_counts[item.redundancy_tag] = tag_counts.get(item.redundancy_tag, 0) + 1
    redundancy_penalty = float(
        sum(max(0, count - 1) * max(0.0, redundancy_discount) for count in tag_counts.values())
    )
    adjusted_total = max(0.0, raw_total - redundancy_penalty)
    scale = max(1e-9, float(saturation_scale))
    saturation_score = float(1.0 - np.exp(-adjusted_total / scale))
    return EvidenceAccumulation(
        raw_total=raw_total,
        adjusted_total=adjusted_total,
        saturation_score=saturation_score,
        redundancy_penalty=redundancy_penalty,
        contribution_count=len(items),
        notes=(
            "Accumulation is evidence-oriented and saturation-aware.",
            "TODO: learn redundancy groups from adjudication history rather than fixed tags.",
        ),
    )


def build_verification_evidence_example(
    graph: StructuralGraph,
    reference_state: Mapping[str, float] | np.ndarray,
    candidate_state: Mapping[str, float] | np.ndarray,
    persistence_score: float,
) -> VerificationEvidenceExample:
    return VerificationEvidenceExample(
        graph=graph_feature_evidence(graph),
        persistence_score=float(persistence_score),
        distance_from_reference=state_distance(reference_state, candidate_state),
    )


def build_adjudication_evidence_example(
    graph_evidence: GraphFeatureEvidence,
    persistence_score: float,
    distance_value: float,
) -> AdjudicationEvidenceExample:
    accumulation = accumulate_evidence(
        [
            EvidenceContribution("graph_fragmentation", graph_evidence.fragmentation_proxy, "graph"),
            EvidenceContribution("graph_bottleneck", graph_evidence.bottleneck_proxy, "graph"),
            EvidenceContribution("state_instability", max(0.0, 1.0 - persistence_score), "temporal"),
            EvidenceContribution("reference_distance", distance_value, "state"),
        ],
        saturation_scale=2.0,
        redundancy_discount=0.2,
    )
    return AdjudicationEvidenceExample(
        saturation_score=accumulation.saturation_score,
        adjusted_total=accumulation.adjusted_total,
        inputs=("graph_fragmentation", "graph_bottleneck", "state_instability", "reference_distance"),
    )


def _degree_concentration(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    total = float(np.sum(values))
    return float(np.max(values) / total) if total > 0 else 0.0


def _connectedness_ratio(node_count: int, component_count: int) -> float:
    if node_count <= 1:
        return 1.0
    return float((node_count - component_count) / (node_count - 1))


def _bottleneck_proxy(degree_values: np.ndarray, graph: StructuralGraph) -> float:
    nx_graph = to_networkx(graph)
    if nx_graph is not None and nx_graph.number_of_edges() > 0:
        try:
            import networkx as nx  # type: ignore

            edge_scores = nx.edge_betweenness_centrality(nx_graph.to_undirected(), weight="weight")
            if edge_scores:
                return float(max(edge_scores.values()))
        except (ImportError, ValueError, RuntimeError):
            pass
    if degree_values.size == 0:
        return 0.0
    total = float(np.sum(degree_values))
    return float(np.max(degree_values) / total) if total > 0 else 0.0
