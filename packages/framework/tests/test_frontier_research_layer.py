from __future__ import annotations

import unittest

from src.research.schemas import ClaimMaturityTag
from src.research import (
    CandidateSignalFactory,
    FrontierResearchEngine,
    FrontierVariableGenerator,
    MechanismComposer,
    ResearchHypothesisRegistry,
    ScenarioPathGenerator,
    StructuralMechanismLibrary,
    ValidationQueue,
)


class FrontierResearchLayerTests(unittest.TestCase):
    def test_mechanism_library_keeps_frontier_work_alive_with_maturity_tags(self) -> None:
        mechanisms = StructuralMechanismLibrary().all()

        self.assertGreaterEqual(len(mechanisms), 14)
        self.assertTrue(all(item.maturity in ClaimMaturityTag for item in mechanisms))
        self.assertIn("deposit_run_operator", {item.name for item in mechanisms})

    def test_variable_generation_is_not_blocked_by_low_maturity(self) -> None:
        variables = FrontierVariableGenerator().generate_all()

        self.assertGreaterEqual(len(variables), 50)
        self.assertTrue(any(item.maturity == ClaimMaturityTag.HYPOTHESIS for item in variables))
        self.assertTrue(all(item.post_generation_constraints for item in variables))
        self.assertIn("banking_MDKX_deposit_beta_gap", {item.name for item in variables})

    def test_mechanism_composition_generates_before_validation(self) -> None:
        compositions = MechanismComposer().compose_all()

        self.assertGreaterEqual(len(compositions), 6)
        self.assertTrue(all(item.generated_variable_names for item in compositions))
        self.assertTrue(any(item.name == "ai_capex_private_credit_refi_loop" for item in compositions))
        self.assertTrue(all("claim guard release" in item.structure_path for item in compositions))

    def test_frontier_engine_attaches_constraints_after_generation(self) -> None:
        bundle = FrontierResearchEngine().generate()

        self.assertGreater(len(bundle.variables), len(bundle.candidate_signals))
        self.assertTrue(bundle.validation_queue)
        self.assertIn("Generation is allowed before validation.", bundle.release_constraints)
        self.assertTrue(any(item.local_state_space == "uk_rates_ldi_MDKX" for item in bundle.variables))

    def test_candidate_signal_factory_marks_hypotheses_without_validation_claims(self) -> None:
        candidates = CandidateSignalFactory(ResearchHypothesisRegistry()).build_all()
        banking = next(item for item in candidates if item.name == "banking_duration_mismatch_signal")

        self.assertEqual(banking.maturity, ClaimMaturityTag.HYPOTHESIS)
        self.assertIn("predicts bank runs", banking.forbidden_claim)
        self.assertTrue(banking.research_admissible)

    def test_scenario_path_generator_outputs_claim_boundary_and_candidate(self) -> None:
        result = ScenarioPathGenerator().generate("Policy backstop restores D but increases X")

        self.assertEqual(result.maturity, ClaimMaturityTag.PROXY_SUPPORTED)
        self.assertTrue(result.operator_sequence)
        self.assertIn("portfolio instruction", result.forbidden_claims)
        self.assertIn("candidate exposure implication", " ".join(result.allowed_claims))
        self.assertIn("before any portfolio use", result.tradable_hypothesis_candidate)

    def test_validation_queue_routes_candidate_without_upgrading_maturity(self) -> None:
        candidate = CandidateSignalFactory().build_all()[0]
        item = ValidationQueue().add(candidate)

        self.assertEqual(item.maturity, candidate.maturity)
        self.assertIn("rolling_origin_oos", item.tests)
        self.assertIn("No full-sample threshold fitting", item.blocking_criteria)

if __name__ == "__main__":
    unittest.main()
