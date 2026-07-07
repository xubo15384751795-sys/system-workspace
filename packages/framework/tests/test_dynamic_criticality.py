from __future__ import annotations

import json
import unittest

import numpy as np

from src.core.models import ChannelBeliefState, DistributionState, ProxyReading, StructuralBeliefState
from src.dynamic.criticality import CriticalityState, build_criticality_state
from src.dynamic.transition import TransitionSignal
from src.dynamic.trajectory import StateTrajectory
from src.derivation.singular_detector import SingularDetectionDiagnostics, ThresholdSingularDetector


class CriticalityDiagnosticTests(unittest.TestCase):
    def test_valid_criticality_state_passes(self) -> None:
        state = CriticalityState(
            case_id="c",
            status="safe",
            nearest_threshold="sigma_composite",
            distance_to_threshold=1.0,
            crossed_conditions=[],
            transition_candidate=False,
            level_risk=0.2,
            transition_risk=None,
            evidence=[],
            interpretation="ok",
        )
        json.dumps(state.to_serializable_dict())

    def test_invalid_status_fails(self) -> None:
        with self.assertRaises(ValueError):
            CriticalityState(
                case_id=None,
                status="green",
                nearest_threshold=None,
                distance_to_threshold=None,
                crossed_conditions=[],
                transition_candidate=False,
                level_risk=None,
                transition_risk=None,
                evidence=[],
                interpretation="x",
            )

    def test_invalid_distance_fails(self) -> None:
        with self.assertRaises(ValueError):
            CriticalityState(
                case_id=None,
                status="unknown",
                nearest_threshold=None,
                distance_to_threshold=-0.1,
                crossed_conditions=[],
                transition_candidate=False,
                level_risk=None,
                transition_risk=None,
                evidence=[],
                interpretation="x",
            )

    def test_invalid_level_risk_fails(self) -> None:
        with self.assertRaises(ValueError):
            CriticalityState(
                case_id=None,
                status="unknown",
                nearest_threshold=None,
                distance_to_threshold=None,
                crossed_conditions=[],
                transition_candidate=False,
                level_risk=1.1,
                transition_risk=None,
                evidence=[],
                interpretation="x",
            )

    def test_invalid_transition_risk_fails(self) -> None:
        with self.assertRaises(ValueError):
            CriticalityState(
                case_id=None,
                status="unknown",
                nearest_threshold=None,
                distance_to_threshold=None,
                crossed_conditions=[],
                transition_candidate=False,
                level_risk=None,
                transition_risk=-0.01,
                evidence=[],
                interpretation="x",
            )

    def test_crossed_status_from_joint_hit(self) -> None:
        diag = SingularDetectionDiagnostics(
            sigma_t=1.0,
            scalar_threshold_hit=False,
            joint_hitting=True,
            distributional_trigger=False,
            forced_realization_pressure=0.8,
            structural_singular_time=0.0,
        )
        state = build_criticality_state(
            sigma_t=1.0,
            sigma_threshold=5.0,
            singular_flag=True,
            diagnostics=diag,
        )
        self.assertEqual(state.status, "crossed")
        self.assertIn("joint_hitting", state.crossed_conditions)

    def test_near_threshold_band(self) -> None:
        state = build_criticality_state(
            sigma_t=1.8,
            sigma_threshold=2.0,
            singular_flag=False,
            diagnostics=None,
            near_ratio=0.85,
            watch_ratio=0.45,
        )
        self.assertEqual(state.status, "near_threshold")

    def test_safe_and_watch_bands(self) -> None:
        safe = build_criticality_state(
            sigma_t=0.2,
            sigma_threshold=2.0,
            singular_flag=False,
            diagnostics=None,
        )
        self.assertEqual(safe.status, "safe")

        watch = build_criticality_state(
            sigma_t=1.0,
            sigma_threshold=2.0,
            singular_flag=False,
            diagnostics=None,
            watch_ratio=0.45,
            near_ratio=0.99,
        )
        self.assertEqual(watch.status, "watch")

    def test_missing_trajectory_leaves_transition_risk_none_without_signal(self) -> None:
        state = build_criticality_state(
            sigma_t=0.5,
            sigma_threshold=2.0,
            singular_flag=False,
            diagnostics=None,
            transition_signal=None,
            state_trajectory=None,
        )
        self.assertIsNone(state.transition_risk)

    def test_level_risk_distinct_from_transition_risk(self) -> None:
        traj = StateTrajectory(times=(0.0, 1.0, 2.0), sigma_values=(0.5, 0.7, 1.6))
        signal = TransitionSignal(pressure_slope=0.1, mode_coupling_index=None)
        state = build_criticality_state(
            sigma_t=1.0,
            sigma_threshold=2.0,
            singular_flag=False,
            diagnostics=None,
            transition_signal=signal,
            state_trajectory=traj,
        )
        self.assertIsNotNone(state.level_risk)
        self.assertIsNotNone(state.transition_risk)
        self.assertNotAlmostEqual(state.level_risk, state.transition_risk)

    def test_singular_detector_schema_unchanged(self) -> None:
        proxy = ProxyReading(
            run_date="2026-03-01",
            M=0.2,
            D=-0.8,
            K=0.8,
            X=0.7,
            directions={"M": "WORSENING", "D": "WORSENING", "K": "WORSENING", "X": "WORSENING"},
            available={"M": True, "D": True, "K": True, "X": True},
            components={"M": 0.2, "D": -0.8, "K": 0.8, "X": 0.7},
        )
        detector = ThresholdSingularDetector(sigma_threshold=10.0)
        sigma_t, flag = detector.detect(proxy, np.ones(6))
        self.assertIsInstance(sigma_t, float)
        self.assertIsInstance(flag, bool)
        assert detector.last_diagnostics is not None
        diag_keys = set(detector.last_diagnostics.to_dict().keys())
        self.assertEqual(
            diag_keys,
            {
                "sigma_t",
                "scalar_threshold_hit",
                "joint_hitting",
                "distributional_trigger",
                "forced_realization_pressure",
                "structural_singular_time",
                "sigma_vector",
            },
        )

    def test_adapter_does_not_mutate_detector_between_calls(self) -> None:
        proxy = ProxyReading(
            run_date="2026-03-01",
            M=0.2,
            D=-0.4,
            K=0.3,
            X=0.1,
            directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
            available={"M": True, "D": True, "K": True, "X": True},
            components={"M": 0.2, "D": -0.4, "K": 0.3, "X": 0.1},
        )
        belief_state = StructuralBeliefState(
            run_date="2026-03-01",
            channels={
                "M": ChannelBeliefState(
                    channel="M",
                    raw_point=0.2,
                    transformed_point=0.18,
                    distribution=DistributionState(
                        family="normal",
                        transform="signed_log1p",
                        mean=0.18,
                        variance=0.09,
                        raw_mean=0.2,
                        raw_variance=0.09,
                        breach_prob=0.2,
                        singular_mass=0.2,
                    ),
                )
            },
            escalation_metrics={
                "sigma_breach_prob": 0.6,
                "sigma_q90": 1.4,
                "max_channel_singular_mass": 0.2,
            },
        )
        detector = ThresholdSingularDetector(
            sigma_threshold=2.0,
            distributional_prob_threshold=0.35,
        )
        sigma_t, flag = detector.detect(proxy, np.ones(6), belief_state=belief_state)
        diag_before = detector.last_diagnostics

        build_criticality_state(
            sigma_t=float(sigma_t),
            sigma_threshold=detector.sigma_threshold,
            singular_flag=bool(flag),
            diagnostics=detector.last_diagnostics,
        )

        sigma_after, flag_after = detector.detect(proxy, np.ones(6), belief_state=belief_state)
        self.assertAlmostEqual(float(sigma_t), float(sigma_after))
        self.assertEqual(bool(flag), bool(flag_after))
        self.assertIsNotNone(diag_before)
        self.assertIsNotNone(detector.last_diagnostics)


if __name__ == "__main__":
    unittest.main()
