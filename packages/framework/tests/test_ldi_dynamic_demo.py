from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core.models import (
    MeanFieldGapState,
    ProxyReading,
    ShadowMassState,
    Snapshot,
    StructuralPrimitiveState,
    StructuralState,
)
from src.dynamic.ldi_demo import (
    DEMO_DISCLAIMER,
    build_ldi_2022_dyn3_dyn4_diagnostics,
    write_ldi_2022_dyn3_dyn4_diagnostics,
)


class LdiDynamicDemoTests(unittest.TestCase):
    def test_demo_payload_contains_required_diagnostics(self) -> None:
        payload = build_ldi_2022_dyn3_dyn4_diagnostics()
        self.assertEqual(payload["disclaimer"], DEMO_DISCLAIMER)
        self.assertIn("diagnostic-only", str(payload["disclaimer"]))

        mismatch = payload["mismatch_map"]
        self.assertEqual(mismatch["profiles"][0]["pair"], ["A", "L"])

        crit = payload["criticality_state"]
        for key in (
            "nearest_threshold",
            "distance_to_threshold",
            "crossed_conditions",
            "transition_candidate",
            "level_risk",
            "transition_risk",
            "interpretation",
        ):
            self.assertIn(key, crit)

        transition = payload["transition"]
        self.assertEqual(transition["source"], "synthetic_demo")

    def test_demo_write_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ldi_2022_dyn3_dyn4_diagnostics.json"
            path = write_ldi_2022_dyn3_dyn4_diagnostics(target)
            self.assertTrue(path.exists())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["mismatch_map"]["profiles"][0]["pair"], ["A", "L"])
            self.assertIn("nearest_threshold", loaded["criticality_state"])

    def test_core_snapshot_structure_unchanged(self) -> None:
        proxy = ProxyReading(
            run_date="2026-04-25",
            M=0.1,
            D=0.2,
            K=0.3,
            X=0.4,
            directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
            available={"M": True, "D": True, "K": True, "X": True},
            components={"M": 0.1, "D": 0.2, "K": 0.3, "X": 0.4},
        )
        state = StructuralState(
            run_date="2026-04-25",
            z_vector=None,
            sigma_t=0.7,
            singular_flag=False,
            leading_channel="M",
            pattern="STABLE_LOCAL",
            anomaly_score=-0.2,
            reflexivity_flags={"credit": True},
            provenance={},
            primitive_state=StructuralPrimitiveState(
                subject=0.1,
                anchor=0.0,
                liquidation_feasibility=0.6,
                verifiability_density=0.5,
                positional_power=0.2,
                latency=0.1,
            ),
            shadow_mass_state=ShadowMassState(
                aggregate_mass=0.4,
                forced_realization_pressure=0.2,
                buckets=(),
            ),
            mean_field_gap=MeanFieldGapState(
                actual_shadow_mass=0.4,
                benchmark_shadow_mass=0.3,
                gap=0.1,
                normalized_gap=0.25,
            ),
        )
        snapshot = Snapshot(
            run_date="2026-04-25",
            run_type="WEEKLY",
            proxy=proxy,
            state=state,
            narrative=None,
            escalation=False,
            escalation_reason=None,
        )
        core = snapshot.core()
        self.assertEqual(core.proxy.M, 0.1)
        self.assertEqual(core.sigma_t, 0.7)


if __name__ == "__main__":
    unittest.main()
