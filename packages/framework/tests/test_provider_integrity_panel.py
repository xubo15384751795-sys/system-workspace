"""OBS-4: LDI ProviderIntegrityPanel demo (ObservationIntegrity JSON)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.dynamic.provider_integrity_panel import (
    build_ldi_2022_provider_integrity_panel_json_dict,
    build_provider_integrity_panel,
    write_ldi_2022_provider_integrity_panel,
)


class TestLdiProviderIntegrityPanel(unittest.TestCase):
    def test_panel_generation_runs(self) -> None:
        obs = build_provider_integrity_panel("ldi_2022", force_synthetic_demo=True)
        self.assertEqual(obs.case_id, "ldi_2022")
        self.assertGreaterEqual(len(obs.checks), 1)

    def test_diagnostic_only_true(self) -> None:
        obs = build_provider_integrity_panel(force_synthetic_demo=True)
        self.assertTrue(obs.diagnostic_only)

    def test_at_least_one_provider_check(self) -> None:
        obs = build_provider_integrity_panel(force_synthetic_demo=True)
        self.assertGreaterEqual(len(obs.checks), 1)
        self.assertTrue(all(hasattr(c, "logical_series") for c in obs.checks))

    def test_staleness_and_static_source_fields_present(self) -> None:
        obs = build_provider_integrity_panel(force_synthetic_demo=True)
        keys_per_check = {k for c in obs.checks for k in c.to_serializable_dict().keys()}
        self.assertIn("staleness_score", keys_per_check)
        self.assertIn("event_window_variance", keys_per_check)
        self.assertIn("issues", keys_per_check)
        self.assertTrue(any(c.staleness_score is not None for c in obs.checks))
        self.assertIsNotNone(obs.static_source_risk)

    def test_demo_synthetic_marked_in_json_wrapper(self) -> None:
        payload = build_ldi_2022_provider_integrity_panel_json_dict(force_synthetic_demo=True)
        self.assertIn("synthetic_or_demo_fields", payload)
        self.assertIsInstance(payload["synthetic_or_demo_fields"], list)
        self.assertGreater(len(payload["synthetic_or_demo_fields"]), 0)
        self.assertIn("data_provenance", payload)
        prov = payload["data_provenance"]
        assert isinstance(prov, dict)
        self.assertIn("synthetic_demo", json.dumps(prov))

    def test_write_json_roundtrip(self) -> None:
        tmp = Path(__file__).resolve().parent / "_tmp_ldi_panel.json"
        try:
            path = write_ldi_2022_provider_integrity_panel(tmp, force_synthetic_demo=True)
            self.assertTrue(path.is_file())
            data = json.loads(path.read_text(encoding="utf-8"))
            oi = data["observation_integrity"]
            self.assertTrue(oi["diagnostic_only"])
            self.assertGreaterEqual(len(oi["checks"]), 1)
        finally:
            if tmp.is_file():
                tmp.unlink()


if __name__ == "__main__":
    unittest.main()
