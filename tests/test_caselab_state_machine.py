from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.state_machine_runtime import (
    evaluate_machine,
    evaluate_world_state,
    load_state_machines,
)
from caselab_context.world_model import query


class StateMachineRuntimeTests(unittest.TestCase):
    def test_machines_loaded(self) -> None:
        machines = load_state_machines()
        self.assertTrue(any(m.get("id") == "credit_cycle" for m in machines))

    def test_credit_cycle_expansion(self) -> None:
        machine = next(m for m in load_state_machines() if m["id"] == "credit_cycle")
        result = evaluate_machine(
            machine,
            {"High Yield OAS": {"date": "2026-06-15", "value": 2.66}},
        )
        self.assertEqual(result.current_state, "expansion")
        self.assertEqual(result.variables.get("credit_stress"), "low")

    def test_credit_cycle_late(self) -> None:
        machine = next(m for m in load_state_machines() if m["id"] == "credit_cycle")
        result = evaluate_machine(
            machine,
            {"High Yield OAS": {"date": "2026-06-15", "value": 4.5}},
        )
        self.assertEqual(result.current_state, "late_cycle")
        self.assertEqual(result.variables.get("credit_stress"), "elevated")

    def test_credit_cycle_crisis(self) -> None:
        machine = next(m for m in load_state_machines() if m["id"] == "credit_cycle")
        result = evaluate_machine(
            machine,
            {"High Yield OAS": {"date": "2026-06-15", "value": 6.5}},
        )
        self.assertEqual(result.current_state, "crisis")

    def test_evaluate_world_state_live_data(self) -> None:
        payload = evaluate_world_state()
        self.assertTrue(payload.get("machines"))
        credit = next(m for m in payload["machines"] if m["id"] == "credit_cycle")
        self.assertIn(credit["current_state"], {"expansion", "late_cycle", "crisis", "recovery", "unknown"})


class WorldModelStateIntegrationTests(unittest.TestCase):
    def test_query_includes_world_state(self) -> None:
        response = query(
            "Goldman Sachs",
            "ipo",
            "public_market",
            evaluate_state=True,
        )
        self.assertIsNotNone(response.world_state)
        self.assertIn("machines", response.world_state or {})
        self.assertIn("credit_cycle_state", response.context_packet)
        self.assertEqual(response.schema_version, "1.2")

    def test_regime_credit_aligned_with_credit_cycle(self) -> None:
        response = query(
            "Goldman Sachs",
            "ipo",
            "public_market",
            evaluate_state=True,
            use_indicator_regime=True,
        )
        credit_state = response.context_packet.get("credit_cycle_state")
        regime_credit = response.context_packet.get("regime", {}).get("credit")
        if credit_state == "expansion":
            self.assertEqual(regime_credit, "expanding")
        elif credit_state == "late_cycle":
            self.assertEqual(regime_credit, "fragile")
        elif credit_state == "crisis":
            self.assertEqual(regime_credit, "contracting")


class AiCapexStateMachineTests(unittest.TestCase):
    def test_ai_capex_machine_loaded(self) -> None:
        machines = load_state_machines()
        self.assertTrue(any(m.get("id") == "ai_capex_cycle" for m in machines))

    def test_ai_capex_growth(self) -> None:
        machine = next(m for m in load_state_machines() if m["id"] == "ai_capex_cycle")
        result = evaluate_machine(
            machine,
            {"NVDA 20d Return": {"date": "2026-06-15", "value": 12.0}},
        )
        self.assertEqual(result.current_state, "growth")
        self.assertEqual(result.variables.get("compute_demand"), "strong")

    def test_ai_capex_saturation(self) -> None:
        machine = next(m for m in load_state_machines() if m["id"] == "ai_capex_cycle")
        result = evaluate_machine(
            machine,
            {"NVDA 20d Return": {"date": "2026-06-15", "value": -6.6}},
        )
        self.assertEqual(result.current_state, "saturation")
        self.assertEqual(result.variables.get("infrastructure_roi_pressure"), "high")

    def test_regime_technology_cycle_aligned_with_ai_capex(self) -> None:
        response = query(
            "Nvidia",
            "raising_guidance",
            "data_center",
            evaluate_state=True,
            use_indicator_regime=True,
        )
        ai_state = response.context_packet.get("ai_capex_cycle_state")
        tech = response.context_packet.get("regime", {}).get("technology_cycle")
        if ai_state == "growth":
            self.assertEqual(tech, "scaling")
        elif ai_state == "bottleneck":
            self.assertEqual(tech, "early")
        elif ai_state == "saturation":
            self.assertEqual(tech, "saturation")


class TransitionRematchTests(unittest.TestCase):
    def test_transition_fields_present_when_active(self) -> None:
        from caselab_context.state_machine_runtime import evaluate_machine, get_machine

        machine = get_machine("ai_capex_cycle")
        assert machine is not None
        # Prior snapshot growth, current saturation -> transition
        world_state = {
            "as_of": "2026-06-16",
            "machines": [
                evaluate_machine(
                    machine,
                    {"NVDA 20d Return": {"date": "2026-06-16", "value": -6.6}},
                ).to_dict(),
            ],
        }
        world_state["machines"][0]["previous_state"] = "growth"
        world_state["machines"][0]["transition"] = {
            "from": "growth",
            "to": "saturation",
            "lookback_days": 20,
        }

        from caselab_context.world_model import _transition_resolver_rematch

        ctx = {
            "matched_rules": ["nv_capex_saturation"],
            "regime": {"technology_cycle": "saturation", "credit": "expanding"},
        }
        warnings = _transition_resolver_rematch(
            ctx,
            actor="Nvidia",
            verb="raising_guidance",
            action_object="data_center",
            regime=ctx["regime"],
            world_state=world_state,
        )
        self.assertIn("state_transitions", ctx)
        self.assertIn("matched_rules_prior", ctx)
        if ctx.get("resolver_rematched_on_transition"):
            self.assertIn("resolver_rules_changed_after_state_transition", warnings)


if __name__ == "__main__":
    unittest.main()
