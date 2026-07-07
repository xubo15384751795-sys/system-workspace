from __future__ import annotations

import unittest

import pandas as pd

from src.core.models import ProxyReading
from src.operators import (
    apply_event_log_to_proxy,
    apply_operator,
    build_default_operator_registry,
    lie_bracket_norm,
    non_commutativity_score,
    operator_commutator_diagnostics,
)


def _proxy() -> ProxyReading:
    return ProxyReading(
        run_date="2026-04-14",
        M=0.20,
        D=-0.20,
        K=0.10,
        X=0.15,
        directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.20, "D": -0.20, "K": 0.10, "X": 0.15},
    )


class StructuralOperatorTests(unittest.TestCase):
    def test_default_registry_contains_operator_taxonomy(self) -> None:
        registry = build_default_operator_registry()
        operators = registry.all()

        self.assertGreaterEqual(len(operators), 20)
        self.assertIsNotNone(registry.get("FUNDING_HAIRCUT"))
        self.assertIsNotNone(registry.get("POLICY_BACKSTOP"))
        self.assertIsNotNone(registry.get("IDENTITY"))

    def test_funding_haircut_is_state_dependent_compression(self) -> None:
        registry = build_default_operator_registry()
        haircut = registry.get("FUNDING_HAIRCUT")
        self.assertIsNotNone(haircut)

        calm = {"M": 0.1, "D": 0.4, "K": 0.1, "X": 0.1}
        stressed = {"M": 0.1, "D": -0.8, "K": 0.1, "X": 0.1}
        calm_after = apply_operator(calm, haircut)  # type: ignore[arg-type]
        stressed_after = apply_operator(stressed, haircut)  # type: ignore[arg-type]

        self.assertLess(calm_after["D"], calm["D"])
        self.assertLess(stressed_after["D"], stressed["D"])
        self.assertGreater(abs(stressed_after["D"] - stressed["D"]), abs(calm_after["D"] - calm["D"]))

    def test_operator_order_is_non_commutative(self) -> None:
        registry = build_default_operator_registry()
        haircut = registry.get("FUNDING_HAIRCUT")
        backstop = registry.get("POLICY_BACKSTOP")
        self.assertIsNotNone(haircut)
        self.assertIsNotNone(backstop)

        score = non_commutativity_score(
            haircut,  # type: ignore[arg-type]
            backstop,  # type: ignore[arg-type]
            {"M": 0.5, "D": -0.6, "K": 0.4, "X": 0.3},
        )

        self.assertGreater(score, 0.0)

    def test_operator_commutator_and_lie_bracket_are_available(self) -> None:
        registry = build_default_operator_registry()
        haircut = registry.get("FUNDING_HAIRCUT")
        backstop = registry.get("POLICY_BACKSTOP")
        self.assertIsNotNone(haircut)
        self.assertIsNotNone(backstop)

        state = {"M": 0.5, "D": -0.6, "K": 0.4, "X": 0.3}
        diagnostics = operator_commutator_diagnostics(
            haircut,  # type: ignore[arg-type]
            backstop,  # type: ignore[arg-type]
            state,
        )

        self.assertGreater(diagnostics["commutator_norm"], 0.0)
        self.assertGreaterEqual(
            lie_bracket_norm(haircut, backstop, state),  # type: ignore[arg-type]
            0.0,
        )

    def test_event_log_maps_to_ordered_operator_sequence(self) -> None:
        registry = build_default_operator_registry()
        event_log = pd.DataFrame(
            [
                {
                    "date": "2026-04-13",
                    "intervention_type": "Funding haircut",
                    "description": "Collateral haircut widened.",
                },
                {
                    "date": "2026-04-14",
                    "intervention_type": "Liquidity facility",
                    "description": "Central bank facility opened.",
                },
            ]
        )

        adjusted, diagnostics = apply_event_log_to_proxy(
            proxy=_proxy(),
            event_log=event_log,
            registry=registry,
            run_date="2026-04-14",
            config={"singular_threshold": 2.0},
        )

        self.assertEqual(diagnostics.operator_count, 2)
        self.assertEqual(diagnostics.sequence_signature, "FUNDING_HAIRCUT -> LIQUIDITY_FACILITY")
        self.assertGreater(diagnostics.non_commutativity_score, 0.0)
        self.assertGreater(diagnostics.path_rank_witness_count, 0)
        self.assertGreater(diagnostics.path_rank_max_output_separation, 0.0)
        self.assertIn("path_rank_witness_count", diagnostics.to_dict())
        self.assertNotEqual(adjusted.D, _proxy().D)


if __name__ == "__main__":
    unittest.main()
