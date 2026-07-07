from __future__ import annotations

import unittest

import numpy as np

from src.core.models import ProxyReading
from src.dynamics.ode_engine import ScipyODEEngine
from src.mechanisms import CHANNELS, build_default_mechanism_registry


def _proxy() -> ProxyReading:
    return ProxyReading(
        run_date="2026-04-14",
        M=0.8,
        D=-0.6,
        K=0.7,
        X=0.5,
        directions={"M": "WORSENING", "D": "WORSENING", "K": "WORSENING", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.8, "D": -0.6, "K": 0.7, "X": 0.5},
    )


class MechanismTests(unittest.TestCase):
    def test_default_mechanisms_are_coarse_grained_to_core_channels(self) -> None:
        registry = build_default_mechanism_registry()
        totals = registry.aggregate(
            _proxy(),
            {
                "leverage_pressure": 1.0,
                "network_concentration": 0.9,
                "policy_delay": 0.4,
            },
        )

        self.assertEqual(set(totals), set(CHANNELS))
        self.assertLess(totals["D"], 0.0)
        self.assertGreater(totals["K"], 0.0)
        self.assertGreater(totals["X"], 0.0)

    def test_registry_can_filter_literature_families(self) -> None:
        registry = build_default_mechanism_registry(enabled_families=["geanakoplos"])
        contributions = registry.contributions(_proxy(), {"collateral_leverage_pressure": 1.0})

        self.assertTrue(contributions)
        self.assertEqual({c.family for c in contributions}, {"geanakoplos"})

    def test_ode_accepts_mechanism_registry_without_changing_state_shape(self) -> None:
        registry = build_default_mechanism_registry(enabled_families=["danielsson_shin_zigrand"])
        z = ScipyODEEngine(mechanism_registry=registry).integrate(_proxy(), {"horizon": 2, "dt": 1.0})

        self.assertEqual(z.shape, (6,))
        self.assertTrue(np.all(np.isfinite(z)))


if __name__ == "__main__":
    unittest.main()
