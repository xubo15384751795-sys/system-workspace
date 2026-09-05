from __future__ import annotations

import importlib.util
import unittest

import numpy as np

from src.core.metrics.distance import pairwise_state_distance_matrix, state_distance
from src.core.metrics.graph_features import (
    EvidenceContribution,
    accumulate_evidence,
    build_adjudication_evidence_example,
    build_verification_evidence_example,
    graph_feature_evidence,
)
from src.core.metrics.persistence import detect_structural_change_points, multi_window_stability
from src.core.models import ProxyReading
from src.core.representation.graph_repr import (
    StructuralEdge,
    build_graph,
    connected_components,
    graph_todo_stub,
    to_networkx,
)
from src.core.representation.topology_stub import available_tda_backends
from src.core.representation.operator_algebra import (
    OperatorStep,
    StructuralStateOperand,
    compose,
)
from src.core.representation.state_space_mapping import DefaultStateSpaceMapping
from src.operators.operator_registry import build_default_operator_registry


def _proxy() -> ProxyReading:
    return ProxyReading(
        run_date="2026-04-01",
        M=1.0,
        D=-0.5,
        K=0.25,
        X=2.0,
        directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 1.0, "D": -0.5, "K": 0.25, "X": 2.0},
    )


class CoreMathArchitectureTests(unittest.TestCase):
    def test_default_state_space_mapping_preserves_existing_formula(self) -> None:
        mapping = DefaultStateSpaceMapping()
        mapped = mapping.map_proxy(_proxy()).as_array()
        expected = np.array([0.5, 0.5, -0.5, 0.25, 0.25, 2.0], dtype=float)
        self.assertTrue(np.array_equal(mapped, expected))
        self.assertEqual(mapping.describe()["mapping_version"], "v1")

    def test_operator_sequence_preserves_order_and_trace(self) -> None:
        registry = build_default_operator_registry()
        haircut = registry.get("FUNDING_HAIRCUT")
        facility = registry.get("LIQUIDITY_FACILITY")
        assert haircut is not None
        assert facility is not None
        sequence = compose(
            OperatorStep(operator=haircut, intensity=1.0, metadata={"event_id": "e1"}),
            OperatorStep(operator=facility, intensity=1.0, metadata={"event_id": "e2"}),
        )

        final_state, trace = sequence.apply(StructuralStateOperand.from_proxy(_proxy()))

        self.assertEqual(sequence.ordering_signature(), ("FUNDING_HAIRCUT", "LIQUIDITY_FACILITY"))
        self.assertEqual(len(trace), 2)
        self.assertEqual(trace[0].step_index, 0)
        self.assertEqual(trace[1].metadata["event_id"], "e2")
        self.assertIn("M", final_state)

    def test_graph_and_metrics_are_lightweight_evidence_generators(self) -> None:
        graph = build_graph(
            _proxy(),
            edges=(
                StructuralEdge(source="M", target="D", weight=0.5, edge_type="couples"),
                StructuralEdge(source="X", target="K", weight=-1.0, edge_type="pressures"),
            ),
        )
        graph_metrics = graph_feature_evidence(graph)
        persistence = multi_window_stability(
            [
                [np.array([0.0, 0.0]), np.array([0.2, 0.2])],
                [np.array([0.1, 0.1]), np.array([0.3, 0.3])],
            ]
        )

        self.assertEqual(graph_metrics.node_count, 4)
        self.assertEqual(graph_metrics.edge_count, 2)
        self.assertEqual(graph_metrics.component_count, 2)
        self.assertIn("M", graph_metrics.weighted_degree)
        self.assertGreaterEqual(persistence.stability_score, 0.0)
        self.assertAlmostEqual(state_distance({"M": 0.0, "D": 0.0}, {"M": 3.0, "D": 4.0}), 5.0)
        self.assertEqual(len(connected_components(graph)), 2)
        networkx_graph = to_networkx(graph)
        if importlib.util.find_spec("networkx") is None:
            self.assertIsNone(networkx_graph)
        else:
            self.assertIsNotNone(networkx_graph)

    def test_evidence_accumulation_and_examples_are_policy_free(self) -> None:
        graph = build_graph(
            _proxy(),
            edges=(
                StructuralEdge(source="M", target="D", weight=0.5, edge_type="couples"),
                StructuralEdge(source="M", target="X", weight=1.5, edge_type="channels"),
                StructuralEdge(source="X", target="K", weight=0.5, edge_type="channels"),
            ),
        )
        graph_evidence = graph_feature_evidence(graph)
        persistence = multi_window_stability(
            [
                [{"M": 0.0, "D": 0.0}, {"M": 0.2, "D": 0.2}],
                [{"M": 0.1, "D": 0.0}, {"M": 0.3, "D": 0.2}],
            ]
        )
        accumulation = accumulate_evidence(
            [
                EvidenceContribution(source="graph_fragmentation", score=graph_evidence.fragmentation_proxy, redundancy_tag="graph"),
                EvidenceContribution(source="graph_bottleneck", score=graph_evidence.bottleneck_proxy, redundancy_tag="graph"),
                EvidenceContribution(source="persistence", score=1.0 - persistence.stability_score, redundancy_tag="temporal"),
            ],
            saturation_scale=2.0,
            redundancy_discount=0.25,
        )
        verification = build_verification_evidence_example(
            graph=graph,
            reference_state={"M": 0.0, "D": 0.0},
            candidate_state={"M": 0.3, "D": 0.4},
            persistence_score=persistence.stability_score,
        )
        adjudication = build_adjudication_evidence_example(
            graph_evidence=graph_evidence,
            persistence_score=persistence.stability_score,
            distance_value=verification.distance_from_reference,
        )

        self.assertGreaterEqual(accumulation.saturation_score, 0.0)
        self.assertLessEqual(accumulation.saturation_score, 1.0)
        self.assertGreaterEqual(verification.distance_from_reference, 0.0)
        self.assertGreaterEqual(adjudication.adjusted_total, 0.0)
        self.assertIn("advanced_builder", graph_todo_stub())
        self.assertEqual(pairwise_state_distance_matrix([{"M": 0.0}, {"M": 1.0}], metric="euclidean").shape, (2, 2))
        self.assertIsInstance(available_tda_backends(), tuple)

    def test_change_point_detection_is_available_with_fallback(self) -> None:
        change_points = detect_structural_change_points(
            [
                np.array([0.0, 0.0]),
                np.array([0.1, 0.1]),
                np.array([4.0, 4.0]),
                np.array([4.2, 4.1]),
            ]
        )
        self.assertIsInstance(change_points, tuple)


if __name__ == "__main__":
    unittest.main()
