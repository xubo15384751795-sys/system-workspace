from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core.models import ProxyReading
from src.runtime import create_system_api


def _config(tmpdir: str) -> dict:
    return {
        "project_name": "Structural Deformation Research System",
        "series_ids": ["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"],
        "history_start": "2026-01-01",
        "default_run_date": "2026-04-20",
        "default_run_type": "WEEKLY",
        "mock_seed": 42,
        "thresholds": {"sigma": 99.0},
        "data": {"root": tmpdir, "version": "runtime-api-test"},
        "ode_params": {"dt": 1.0, "horizon": 2},
        "output": {"dir": tmpdir, "export_image": False},
        "event_log": {"path": str(Path(tmpdir) / "event_log.jsonl")},
        "text_log": {"path": str(Path(tmpdir) / "texts.jsonl")},
        "ml": {"enabled": False},
        "data_sources": {"enabled": ["fred"], "composite_max_workers": 2},
        "operators": {"enabled": True, "lookback_days": 30, "max_events": 5},
    }


def _proxy(run_date: str = "2026-04-21") -> ProxyReading:
    return ProxyReading(
        run_date=run_date,
        M=0.2,
        D=-0.1,
        K=0.3,
        X=0.1,
        directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.2, "D": -0.1, "K": 0.3, "X": 0.1},
    )


class StructuralSystemAPITests(unittest.TestCase):
    def test_runtime_api_runs_snapshot_and_replays_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            api = create_system_api(_config(tmpdir), use_mock=True)

            snapshot = api.run_snapshot("2026-04-20", "WEEKLY")
            replay = api.replay_window("2026-04-01", "2026-04-30")

            self.assertEqual(snapshot["run_date"], "2026-04-20")
            self.assertIn("assets", snapshot)
            self.assertIn("evidence", snapshot)
            self.assertIn("datahub_manifest", snapshot["state"]["provenance"])
            self.assertEqual(replay["count"], 1)
            self.assertEqual(replay["snapshots"][0]["run_date"], "2026-04-20")

    def test_runtime_api_accepts_candidate_proxy_without_data_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            api = create_system_api(_config(tmpdir), use_mock=True)

            payloads = api.submit_candidates(_proxy(), run_type="MANUAL_CANDIDATE", persist=True)
            stored = api.get_snapshot("2026-04-21")

            self.assertEqual(len(payloads), 1)
            self.assertEqual(payloads[0]["run_type"], "MANUAL_CANDIDATE")
            self.assertIsNotNone(stored)

    def test_runtime_api_can_submit_event_to_shared_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _config(tmpdir)
            api = create_system_api(cfg, use_mock=True)

            event = api.submit_event(
                {
                    "date": "2026-04-22",
                    "actor": "CENTRAL_BANK",
                    "intervention_type": "Liquidity facility",
                    "affected_proxy": ["D", "K"],
                }
            )

            log_path = Path(cfg["event_log"]["path"])
            self.assertEqual(event["actor"], "CENTRAL_BANK")
            self.assertTrue(log_path.exists())
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["intervention_type"], "Liquidity facility")

    def test_runtime_api_exposes_asset_catalog_and_evidence_definitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            api = create_system_api(_config(tmpdir), use_mock=True)
            api.run_snapshot("2026-04-20", "WEEKLY")

            assets = api.describe_assets()
            lineage = api.asset_lineage("snapshot")
            definitions = api.list_evidence_definitions()
            evidence = api.get_snapshot_evidence("2026-04-20")

            self.assertTrue(any(item["asset_name"] == "snapshot" for item in assets))
            self.assertIsNotNone(lineage)
            assert lineage is not None
            self.assertIn("adjudicated_signals", lineage["upstream_assets"])
            self.assertTrue(any(item["family"] == "graph_features" for item in definitions))
            self.assertIsNotNone(evidence)
            assert evidence is not None
            self.assertIn("graph_features", evidence["families"])
            self.assertIn("canonical_chain", evidence)
            from system_runtime.canonical_ids import validate_chain

            validate_chain(evidence["canonical_chain"])
            self.assertEqual(evidence["canonical_chain"]["measurement"]["derivation"], "PROXY_DERIVED")
            self.assertEqual(evidence["canonical_chain"]["evidence"]["evidence_role"], "DERIVED")
            self.assertIs(evidence["canonical_chain"]["claim"]["provenance"]["promotion_allowed"], False)

    def test_runtime_api_exposes_datahub_fetchers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            api = create_system_api(_config(tmpdir), use_mock=True)

            providers = api.available_data_providers()
            presets = api.available_structural_presets()
            structural = api.fetch_structural_presets(
                ["mismatch_policy_funding_gap_us", "dof_funding_access_us"],
                start="2026-01-01",
                end="2026-01-15",
            )
            series = api.fetch_series(
                [{"provider": "fred", "series_id": "DFF"}],
                start="2026-01-01",
                end="2026-01-15",
            )
            filings = api.fetch_filings(
                [
                    {
                        "provider": "sec",
                        "cik": "320193",
                        "channel": "X",
                        "measurement_block": "verifiability",
                        "evidence_role": "validation",
                        "jurisdiction_or_scope": "issuer_core",
                    }
                ],
                start="2026-01-01",
                end="2026-01-15",
            )
            positions = api.fetch_positions(
                [
                    {
                        "provider": "cftc",
                        "resource": "dummy",
                        "market_name": "Mock Market",
                        "channel": "D",
                        "measurement_block": "hedge_breadth",
                        "evidence_role": "validation",
                        "jurisdiction_or_scope": "us_futures",
                    }
                ],
                start="2026-01-01",
                end="2026-01-15",
            )

            self.assertIn("series", providers)
            self.assertGreaterEqual(len(presets), 1)
            self.assertEqual(structural["kind"], "structural_presets")
            self.assertEqual(len(structural["items"]), 2)
            self.assertEqual(series["kind"], "series")
            self.assertEqual(len(series["items"]), 1)
            self.assertEqual(series["items"][0]["metadata"]["preset_name"], "mismatch_policy_funding_gap_us")
            self.assertEqual(len(filings["items"]), 1)
            self.assertEqual(len(positions["items"]), 1)


if __name__ == "__main__":
    unittest.main()
