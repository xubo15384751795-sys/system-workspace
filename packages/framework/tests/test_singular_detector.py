from __future__ import annotations

import unittest

import numpy as np

from src.core.models import ChannelBeliefState, DistributionState, ProxyReading, StructuralBeliefState
from src._legacy.data.data_sources import MockDataSource
from src.dynamics.ode_engine import ScipyODEEngine
from src.derivation.proxy_builder import DefaultProxyBuilder
from src.derivation.singular_detector import ThresholdSingularDetector


class SingularDetectorTests(unittest.TestCase):
    def test_detect_non_singular_on_normal_mock_input(self) -> None:
        source = MockDataSource(seed=3)
        raw = source.fetch(["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"], "2026-01-01", "2026-03-01")
        proxy = DefaultProxyBuilder().build(raw, "2026-03-01")
        z = ScipyODEEngine().integrate(proxy, {"horizon": 2, "dt": 1.0})

        sigma_t, flag = ThresholdSingularDetector(sigma_threshold=4.0).detect(proxy, z)
        self.assertIsInstance(sigma_t, float)
        self.assertFalse(flag)

    def test_detect_singular_on_stress_input(self) -> None:
        proxy = ProxyReading(
            run_date="2026-03-01",
            M=0.8,
            D=-1.0,
            K=0.7,
            X=0.6,
            directions={"M": "WORSENING", "D": "WORSENING", "K": "WORSENING", "X": "WORSENING"},
            available={"M": True, "D": True, "K": True, "X": True},
            components={"M": 0.8, "D": -1.0, "K": 0.7, "X": 0.6},
        )
        z = np.array([5.0, 5.0, 3.0, 3.0, 2.0, 2.0], dtype=float)

        sigma_t, flag = ThresholdSingularDetector(sigma_threshold=2.0).detect(proxy, z)
        self.assertGreaterEqual(sigma_t, 2.0)
        self.assertTrue(flag)

    def test_joint_hitting_records_structural_singular_time(self) -> None:
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

        _, flag = detector.detect(proxy, np.ones(6))

        self.assertTrue(flag)
        self.assertIsNotNone(detector.last_diagnostics)
        assert detector.last_diagnostics is not None
        self.assertTrue(detector.last_diagnostics.joint_hitting)
        self.assertEqual(detector.last_diagnostics.structural_singular_time, 0.0)
        vector = detector.last_diagnostics.sigma_vector
        self.assertIsNotNone(vector)
        assert vector is not None
        payload = vector.to_dict()
        for field in (
            "M",
            "D",
            "K",
            "X_PRE",
            "X_REALIZED",
            "operator_penalties",
            "dominant_channel",
            "cofire_count",
            "reduction_warning",
        ):
            self.assertIn(field, payload)
        self.assertGreaterEqual(payload["cofire_count"], 3)

    def test_sigma_uses_negative_dof_and_positive_stress_channels(self) -> None:
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

        sigma_t, flag = ThresholdSingularDetector(
            sigma_threshold=2.0,
            w_mismatch=0.25,
            w_dof=0.25,
            w_curvature=0.25,
            w_shadow=0.25,
        ).detect(proxy, np.ones(6))

        self.assertAlmostEqual(sigma_t, 0.25)
        self.assertFalse(flag)

    def test_distributional_tail_risk_can_trigger_escalation(self) -> None:
        proxy = ProxyReading(
            run_date="2026-03-01",
            M=0.2,
            D=-0.2,
            K=0.1,
            X=0.1,
            directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
            available={"M": True, "D": True, "K": True, "X": True},
            components={"M": 0.2, "D": -0.2, "K": 0.1, "X": 0.1},
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

        sigma_t, flag = ThresholdSingularDetector(
            sigma_threshold=2.0,
            distributional_prob_threshold=0.35,
        ).detect(proxy, np.ones(6), belief_state=belief_state)

        self.assertLess(sigma_t, 2.0)
        self.assertTrue(flag)


if __name__ == "__main__":
    unittest.main()
