from __future__ import annotations

import unittest

import pandas as pd

from src.benchmarks.benchmark_registry import BENCHMARK_FAMILIES, COMPONENT_RIVALS
from src.core.models import ProxyReading
from src.diagnostics.structural_diagnostic import build_structural_diagnostic_state


class StructuralDiagnosticTests(unittest.TestCase):
    def test_diagnostic_state_outputs_components_before_aggregate(self) -> None:
        idx = pd.date_range("2023-03-01", periods=10, freq="D")
        raw = pd.DataFrame(
            {
                "NFCI": range(10),
                "VIXCLS": range(10, 20),
                "BAMLH0A0HYM2": range(5, 15),
                "NFCILEVERAGE": range(3, 13),
            },
            index=idx,
        )
        proxy = ProxyReading(
            run_date="2023-03-10",
            M=0.91,
            D=-0.18,
            K=0.61,
            X=0.76,
            directions={"M": "WORSENING", "D": "WORSENING", "K": "WORSENING", "X": "WORSENING"},
            available={"M": True, "D": True, "K": True, "X": True},
            components={
                "M_POLICY_ANCHOR": 0.44,
                "M_FUNDING_ANCHOR": 0.88,
                "M_COLLATERAL_ANCHOR": 0.73,
                "M_CREDIT_ANCHOR": 0.69,
                "M_VERIFIABILITY_ANCHOR": 0.95,
                "D_MARKET_DEPTH": -0.22,
                "D_HEDGE_BREADTH": -0.35,
                "D_FUNDING_ACCESS": -0.14,
                "D_LIQUIDATION_PATHS": -0.19,
                "K_IV_SURFACE_DEFORMATION": 0.58,
                "K_JUMP_DISCONTINUITY": 0.49,
                "K_TAIL_CONVEXITY": 0.71,
                "K_TRANSITION_INSTABILITY": 0.64,
                "X_HIDDEN_LEVERAGE": 0.72,
                "X_SHADOW_SUBSTITUTION": 0.66,
                "X_MATURITY_MISMATCH": 0.81,
                "X_VALUATION_LAG": 0.85,
            },
        )

        state = build_structural_diagnostic_state("2023-03-10", proxy, 0.84, raw)
        payload = state.to_dict()

        self.assertEqual(payload["components"]["D_stress"], 0.18)
        self.assertEqual(payload["subcomponents"]["M"]["verifiability_anchor"], 0.95)
        self.assertIn("K_resid_vs_vol_jump_tail", payload["residual_diagnostics"])
        self.assertIn("rejection_flags", payload)
        self.assertNotIn("NFCI", proxy.components)

    def test_benchmark_registry_keeps_compression_surface_separate(self) -> None:
        self.assertIn("NFCI", BENCHMARK_FAMILIES["aggregate_stress"]["primary"])
        self.assertEqual(COMPONENT_RIVALS["K_proxy"], "volatility_jump_tail_index")


if __name__ == "__main__":
    unittest.main()
