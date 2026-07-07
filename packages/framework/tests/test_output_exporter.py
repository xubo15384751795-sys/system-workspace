from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.semantic

import numpy as np

from src.core.models import (
    ChannelBeliefState,
    DistributionState,
    NarrativeReading,
    ProxyReading,
    Snapshot,
    StructuralBeliefState,
    StructuralState,
)
from src.data.snapshot_store import DuckDBSnapshotStore
from src.output.output_exporter import _render_html, export_snapshot_artifacts, snapshot_to_dict
from src.output.result_renderer import render_latest_result
from src.output.run_package import export_research_run_package


def _sample_snapshot() -> Snapshot:
    proxy = ProxyReading(
        run_date="2026-04-14",
        M=0.1,
        D=0.2,
        K=0.3,
        X=0.4,
        directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.1, "D": 0.2, "K": 0.3, "X": 0.4},
    )
    state = StructuralState(
        run_date="2026-04-14",
        z_vector=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]),
        sigma_t=0.8,
        singular_flag=False,
        leading_channel="NONE",
        pattern="STABLE_LOCAL",
        anomaly_score=-0.1,
        reflexivity_flags={"credit": False},
        provenance={"git_hash": "abc"},
        belief_state=StructuralBeliefState(
            run_date="2026-04-14",
            channels={
                "M": ChannelBeliefState(
                    channel="M",
                    raw_point=0.1,
                    transformed_point=0.095,
                    distribution=DistributionState(
                        family="normal",
                        transform="signed_log1p",
                        mean=0.095,
                        variance=0.04,
                        raw_mean=0.1,
                        raw_variance=0.04,
                        breach_prob=0.1,
                        singular_mass=0.1,
                    ),
                )
            },
            escalation_metrics={"sigma_breach_prob": 0.12},
        ),
    )
    narrative = NarrativeReading(
        run_date="2026-04-14",
        ai_unicorn="ANCHORED",
        clo_cmbs="ANCHORED",
        policy="ANCHORED",
        drift_scores={"ai_unicorn": 0.0},
    )
    return Snapshot(
        run_date="2026-04-14",
        run_type="WEEKLY",
        proxy=proxy,
        state=state,
        narrative=narrative,
        escalation=False,
        escalation_reason=None,
    )


class OutputExporterTests(unittest.TestCase):
    def test_export_snapshot_artifacts_writes_html_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = export_snapshot_artifacts(
                snapshot=_sample_snapshot(),
                output_dir=tmpdir,
                export_image=False,
            )
            self.assertIn("html", artifacts)
            self.assertIn("json", artifacts)
            self.assertNotIn("png", artifacts)

    def test_render_latest_result_writes_stable_report_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            lab_root = root / "structural_lab"
            output_root = root / "Output"
            duckdb_path = lab_root / "runtime" / "system.duckdb"
            store = DuckDBSnapshotStore(path=str(duckdb_path), data_root=str(lab_root))
            store.save(_sample_snapshot())

            artifacts = render_latest_result(
                {
                    "data": {"system_root": str(root), "lab_root": str(lab_root)},
                    "runtime": {"duckdb_path": str(duckdb_path)},
                    "output": {"dir": str(output_root), "export_image": False},
                }
            )

            latest_html = Path(artifacts["latest_html"])
            latest_json = Path(artifacts["latest_json"])
            self.assertTrue(latest_html.exists())
            self.assertTrue(latest_json.exists())
            self.assertIn("2026-04-14", latest_html.read_text(encoding="utf-8"))
            self.assertTrue(Path(artifacts["run_package"]).exists())
            self.assertTrue(Path(artifacts["executive_summary"]).exists())

    def test_export_research_run_package_writes_standard_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            artifacts = export_research_run_package(
                snapshot=_sample_snapshot(),
                config={
                    "data": {"backend": "legacy"},
                    "harvester": {"release": "latest", "exports_root": "/tmp/exports"},
                    "output": {"dir": str(output_root), "export_image": False},
                },
                output_root=output_root,
                export_image=False,
            )

            package_dir = Path(artifacts["package_dir"])
            expected = [
                "reports/executive_summary.md",
                "reports/report.html",
                "reports/dashboard_snapshot.json",
                "run_manifest.json",
                "artifacts.json",
                "figures",
                "tables/component_snapshot.csv",
                "tables/benchmark_comparison.csv",
                "machine/snapshot.json",
                "machine/structural_state.csv",
                "machine/proxy_readings.csv",
                "traces/operator_trace.jsonl",
                "config_snapshot.json",
                "diagnostics/rejection_flags.json",
                "diagnostics/residual_tests.json",
                "diagnostics/validation_report.md",
                "logs/run.log",
            ]
            for rel in expected:
                self.assertTrue((package_dir / rel).exists(), rel)
            config_snapshot = json.loads((package_dir / "config_snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(config_snapshot["captured_status"], "captured")
            self.assertEqual(config_snapshot["run_id"], artifacts["run_id"])
            trace_header = json.loads((package_dir / "traces" / "operator_trace.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(trace_header["status"], "complete")
            self.assertNotEqual(trace_header.get("event"), "operator_trace_unavailable")
            self.assertIn(
                "Structural Risk Run",
                (package_dir / "reports" / "executive_summary.md").read_text(encoding="utf-8"),
            )
            self.assertTrue((output_root / "deformation_runs" / "latest").exists())

    def test_snapshot_dict_includes_interpretation_layer(self) -> None:
        payload = snapshot_to_dict(_sample_snapshot())

        self.assertIn("interpretation", payload)
        self.assertIn("snapshot_core", payload)
        self.assertIn("snapshot_extension", payload)
        self.assertEqual(payload["snapshot_core"]["layer"], "paper_aligned")
        self.assertEqual(payload["snapshot_extension"]["layer"], "exploratory")
        self.assertEqual(payload["interpretation"]["pattern"], "STABLE_LOCAL")
        self.assertIn("recommended_actions", payload["interpretation"])
        self.assertIn("belief_state", payload["state"])
        self.assertEqual(payload["state"]["belief_state"]["escalation_metrics"]["sigma_breach_prob"], 0.12)
        self.assertIn("SigmaVector", payload["state"])
        for field in (
            "M",
            "D",
            "K",
            "X_PRE",
            "X_REALIZED",
            "operator_penalties",
            "dominant_channel",
            "cofire_count",
            "reduction_warning",
        ):
            self.assertIn(field, payload["state"]["SigmaVector"])
        # V is NOT_IMPLEMENTED but has a heuristic projection — verify both labels
        self.assertEqual(payload["concept_registry"]["V"]["status"], "NOT_IMPLEMENTED")
        self.assertEqual(payload["concept_registry"]["V"]["projection_status"], "HEURISTIC_NOT_MEASUREMENT")
        self.assertEqual(payload["concept_registry"]["V"]["do_not_interpret_as"], "V (Verifiability density)")
        self.assertIn("V-to-X claims are not empirically supported", payload["concept_registry"]["V"]["warning"])
        # S, L, tau are also NOT_IMPLEMENTED with projections
        for concept in ("S", "L", "tau"):
            self.assertEqual(payload["concept_registry"][concept]["status"], "NOT_IMPLEMENTED")
            self.assertEqual(payload["concept_registry"][concept]["projection_status"], "HEURISTIC_NOT_MEASUREMENT")
            self.assertIn("do_not_interpret_as", payload["concept_registry"][concept])

    def test_snapshot_core_excludes_exploratory_ml_claims(self) -> None:
        payload = snapshot_to_dict(_sample_snapshot())

        core_state = payload["snapshot_core"]["state"]
        extension = payload["snapshot_extension"]

        self.assertNotIn("anomaly_score", core_state)
        self.assertNotIn("belief_state", core_state)
        self.assertNotIn("reflexivity_flags", core_state)
        self.assertEqual(extension["anomaly_score"], -0.1)
        self.assertIn("belief_state", extension)

    def test_render_html_formats_values_and_humanizes_sections(self) -> None:
        payload = snapshot_to_dict(_sample_snapshot())
        payload["proxy"]["directions"] = {"M": "WORSENING", "D": "STABLE", "K": "IMPROVING", "X": "UNKNOWN"}
        payload["proxy"]["M"] = 0.21488771763622294
        payload["state"]["sigma_t"] = 0.18815534757786734
        payload["state"]["anomaly_score"] = -0.3140308124256521
        payload["state"]["singular_flag"] = False
        payload["state"]["operator_diagnostics"] = {}
        payload["narrative"]["drift_scores"] = {"ai_unicorn": 0.0, "clo_cmbs": 0.0012, "policy": 0.0}

        html = _render_html(payload)

        self.assertIn("0.215", html)
        self.assertIn("0.188", html)
        self.assertIn("-0.314", html)
        self.assertIn("Worsening", html)
        self.assertIn("Improving", html)
        self.assertIn("Singular regime", html)
        self.assertIn("Proxy Reduction Warnings", html)
        self.assertIn("Concept Implementation Registry", html)
        self.assertIn("V-to-X claims are not empirically supported", html)
        self.assertIn("No operator activity recorded for this run.", html)
        self.assertIn("<th>Escalation</th><td>No</td>", html)
        self.assertIn("drift 0.000", html)


if __name__ == "__main__":
    unittest.main()
