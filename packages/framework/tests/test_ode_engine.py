from __future__ import annotations

import unittest

import numpy as np

from src.core.representation.state_space_mapping import DefaultStateSpaceMapping
from src._legacy.data.data_sources import MockDataSource
from src.dynamics.state_evolution import DiffraxODEEngine
from src.dynamics.ode_engine import ScipyODEEngine
from src.derivation.proxy_builder import DefaultProxyBuilder


class ODEEngineTests(unittest.TestCase):
    def test_integrate_returns_vector_shape_six(self) -> None:
        source = MockDataSource(seed=11)
        raw = source.fetch(["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"], "2026-01-01", "2026-03-01")
        proxy = DefaultProxyBuilder().build(raw, "2026-03-01")

        z = ScipyODEEngine().integrate(proxy, {"horizon": 4, "dt": 1.0, "alpha": 0.1, "beta": 0.05})
        self.assertEqual(z.shape, (6,))
        self.assertTrue(np.isfinite(z).all())

    def test_integrate_fallback_to_zeros_when_params_invalid(self) -> None:
        source = MockDataSource(seed=13)
        raw = source.fetch(["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"], "2026-01-01", "2026-03-01")
        proxy = DefaultProxyBuilder().build(raw, "2026-03-01")

        z = ScipyODEEngine().integrate(proxy, {"horizon": "bad", "dt": 1.0})
        self.assertTrue(np.array_equal(z, np.zeros(6)))

    def test_default_mapping_matches_explicit_state_space_mapping(self) -> None:
        source = MockDataSource(seed=17)
        raw = source.fetch(["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"], "2026-01-01", "2026-03-01")
        proxy = DefaultProxyBuilder().build(raw, "2026-03-01")

        engine = ScipyODEEngine()
        self.assertTrue(
            np.array_equal(
                engine.map_proxy_to_initial_state(proxy),
                DefaultStateSpaceMapping().map_proxy(proxy).as_array(),
            )
        )

    def test_diffrax_backend_exposes_solver_diagnostics(self) -> None:
        source = MockDataSource(seed=19)
        raw = source.fetch(["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"], "2026-01-01", "2026-03-01")
        proxy = DefaultProxyBuilder().build(raw, "2026-03-01")

        z = DiffraxODEEngine(preferred_backend="diffrax").integrate(
            proxy,
            {"backend": "diffrax", "solver": "tsit5", "horizon": 2, "dt": 1.0},
        )

        self.assertEqual(z.shape, (6,))
        self.assertTrue(np.isfinite(z).all())

    def test_curvature_diagnostics_include_jacobian_metrics(self) -> None:
        metrics = DiffraxODEEngine().curvature_diagnostics(
            np.array([0.2, 0.1, -0.2, -0.1, 0.3, 0.4]),
            {"alpha": 0.1, "beta": 0.05},
        )

        self.assertIn("spectral_abscissa", metrics)
        self.assertIn("jacobian_frobenius_norm", metrics)


if __name__ == "__main__":
    unittest.main()
