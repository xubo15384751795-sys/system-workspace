from __future__ import annotations

import unittest

import numpy as np

from src.core.models import ProxyReading
from src.derivation.singular_detector import ThresholdSingularDetector
from src.derivation.structural_layers import build_structural_layers


def _proxy() -> ProxyReading:
    return ProxyReading(
        run_date="2026-04-24",
        M=0.8,
        D=-0.8,
        K=0.8,
        X=0.7,
        directions={"M": "WORSENING", "D": "WORSENING", "K": "WORSENING", "X": "WORSENING"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.8, "D": -0.8, "K": 0.8, "X": 0.7},
    )


class StructuralLayerTests(unittest.TestCase):
    def test_builds_primitive_shadow_and_mean_field_layers(self) -> None:
        bundle = build_structural_layers(_proxy())

        self.assertGreaterEqual(bundle.primitive_state.liquidation_feasibility, 0.0)
        self.assertIn("D", bundle.primitive_state.derived)
        self.assertEqual(len(bundle.shadow_mass_state.buckets), 4)
        self.assertGreater(bundle.shadow_mass_state.aggregate_mass, 0.0)
        self.assertGreaterEqual(bundle.shadow_mass_state.forced_realization_pressure, 0.0)
        self.assertGreaterEqual(bundle.mean_field_gap.gap, 0.0)

    def test_shadow_pressure_can_trigger_joint_singular_hitting(self) -> None:
        proxy = _proxy()
        bundle = build_structural_layers(proxy)

        sigma_t, flag = ThresholdSingularDetector(
            sigma_threshold=10.0,
            dof_collapse_threshold=-0.65,
            curvature_spike_threshold=0.65,
            forced_realization_threshold=0.1,
        ).detect(
            proxy,
            np.ones(6),
            shadow_mass_state=bundle.shadow_mass_state,
        )

        self.assertLess(sigma_t, 10.0)
        self.assertTrue(flag)

    def test_split_x_pre_and_realized_have_separate_layer_roles(self) -> None:
        proxy = ProxyReading(
            run_date="2026-04-24",
            M=0.2,
            D=-0.4,
            K=0.3,
            X=0.9,
            X_PRE=0.2,
            X_REALIZED=0.9,
            directions={"M": "STABLE", "D": "WORSENING", "K": "STABLE", "X": "WORSENING"},
            available={"M": True, "D": True, "K": True, "X": True, "X_PRE": True, "X_REALIZED": True},
            components={"M": 0.2, "D": -0.4, "K": 0.3, "X": 0.9, "X_PRE": 0.2, "X_REALIZED": 0.9},
        )

        bundle = build_structural_layers(proxy)

        self.assertAlmostEqual(bundle.primitive_state.derived["X_PRE_proxy_floor"], 0.2)
        self.assertAlmostEqual(bundle.primitive_state.derived["X_REALIZED_proxy_floor"], 0.9)
        self.assertAlmostEqual(bundle.shadow_mass_state.metadata["base_x"], 0.2)
        self.assertAlmostEqual(bundle.shadow_mass_state.metadata["observed_realization"], 0.9)


if __name__ == "__main__":
    unittest.main()
