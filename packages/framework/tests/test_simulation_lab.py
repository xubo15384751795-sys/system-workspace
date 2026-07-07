from __future__ import annotations

import unittest

from src.simulation import AgentBasedLab, ToyABMScenario, run_crisis_case, run_crisis_cases, leverage_funding_phase_diagram


class SimulationLabTests(unittest.TestCase):
    def test_agent_based_lab_coarse_grains_to_core_proxy_paths(self) -> None:
        lab = AgentBasedLab()
        frame = lab.simulate(
            ToyABMScenario(
                steps=12,
                seed=1,
                funding_stress=0.5,
                collateral_shock=0.2,
                network_concentration=0.8,
                policy_delay=6,
            )
        )

        self.assertEqual(len(frame), 12)
        self.assertTrue({"M", "D", "K", "X", "Sigma", "singular_flag"}.issubset(frame.columns))
        self.assertTrue(frame["Sigma"].ge(0.0).all())

        summary = lab.summarize(frame)
        self.assertGreaterEqual(summary.max_sigma, 0.0)
        self.assertGreaterEqual(summary.singular_probability, 0.0)

    def test_phase_diagram_returns_regime_map(self) -> None:
        frame = leverage_funding_phase_diagram(
            leverage_speeds=[0.1, 0.3],
            funding_stresses=[0.1, 0.7],
            base=ToyABMScenario(steps=8),
        )

        self.assertEqual(len(frame), 4)
        self.assertTrue({"regime", "singular_probability", "max_sigma"}.issubset(frame.columns))

    def test_singular_thresholds_are_reachable_for_stress_case(self) -> None:
        lab = AgentBasedLab()
        frame = lab.simulate(
            ToyABMScenario(
                steps=24,
                seed=3,
                initial_leverage=8.0,
                target_leverage=9.0,
                funding_stress=0.9,
                collateral_shock=0.4,
                network_concentration=0.95,
                dealer_capacity=0.35,
                policy_delay=20,
            )
        )

        self.assertTrue(frame["singular_flag"].any())

    def test_named_crisis_cases_return_structural_summaries(self) -> None:
        result = run_crisis_case("subprime_2008")
        frame = run_crisis_cases(["subprime_2008", "ltcm_1998"])

        self.assertEqual(result.name, "subprime_2008")
        self.assertIn("funding haircut", result.mechanism_chain)
        self.assertEqual(len(frame), 2)
        self.assertTrue({"case", "regime", "max_sigma", "first_singular_step"}.issubset(frame.columns))
        self.assertTrue(frame["terminal_singular_flag"].isin([True, False]).all())


if __name__ == "__main__":
    unittest.main()
