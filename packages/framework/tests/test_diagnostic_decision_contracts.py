from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.diagnostics.morphology_classifier import classify_morphology
from src.diagnostics.rejection_gates import evaluate_rejection_gates


class DiagnosticDecisionContractTests(unittest.TestCase):
    def test_morphology_label_branches_are_locked_to_inputs(self) -> None:
        cases = [
            (
                {"M_anchor_mismatch": 0.7, "D_stress": 0.8},
                {},
                {},
                "anchor_mismatch_plus_path_contraction",
            ),
            (
                {"K_transition_deformation": 0.7, "D_stress": 0.8},
                {},
                {},
                "transition_deformation_with_path_collapse",
            ),
            (
                {"X_shadow_accumulation": 0.8},
                {},
                {"NFCI": 0.1},
                "latent_shadow_accumulation",
            ),
            (
                {"M_anchor_mismatch": 0.1, "D_path_feasibility": 0.1, "K_transition_deformation": 0.1, "X_shadow_accumulation": 0.1},
                {},
                {"NFCI": 0.9},
                "generic_aggregate_stress",
            ),
            (
                {"X_shadow_accumulation": 0.8, "K_transition_deformation": 0.7},
                {},
                {},
                "shadow_stock_with_transition_deformation",
            ),
            (
                {"M_anchor_mismatch": 0.1, "D_path_feasibility": 0.1, "K_transition_deformation": 0.1, "X_shadow_accumulation": 0.1},
                {},
                {},
                "mixed_or_low_structural_signal",
            ),
        ]

        for components, residuals, benchmarks, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    classify_morphology(components, residuals=residuals, benchmarks=benchmarks).label,
                    expected,
                )

    def test_rejection_gate_flags_are_locked_to_negative_evidence(self) -> None:
        flags = evaluate_rejection_gates(
            incremental_metrics={
                "sigma_incremental_auc": -0.01,
                "sigma_incremental_brier_improvement": 0.0,
                "k_incremental_auc_after_vol_jump_tail": 0.0,
                "k_incremental_brier_improvement": -0.01,
            },
            event_coherence={"ldi_2022": True, "svb_2023": False},
            portfolio_metrics={
                "overlay_excess_return": -0.01,
                "overlay_drawdown_improvement": 0.0,
                "overlay_left_tail_improvement": 0.0,
            },
        )

        self.assertTrue(flags["sigma_no_incremental_discrimination"])
        self.assertTrue(flags["k_block_no_increment_after_vol_jump_tail"])
        self.assertTrue(flags["case_sequence_no_coherent_response"])
        self.assertTrue(flags["portfolio_overlay_underperforms_without_tail_benefit"])

    def test_rejection_gate_flags_cross_loading_and_sigma_nfci_collinearity(self) -> None:
        idx = pd.date_range("2026-01-01", periods=24, freq="D")
        base = np.linspace(0.0, 1.0, len(idx))
        channels = pd.DataFrame({"M": base, "D": base * 1.01, "K": base[::-1]}, index=idx)
        sigma = pd.Series(base, index=idx)
        benchmarks = pd.DataFrame({"NFCI": base * 2.0}, index=idx)

        flags = evaluate_rejection_gates(channels=channels, sigma=sigma, benchmarks=benchmarks)

        self.assertTrue(flags["proxy_blocks_cross_loading_too_high"])
        self.assertTrue(flags["sigma_no_incremental_discrimination"])


if __name__ == "__main__":
    unittest.main()
