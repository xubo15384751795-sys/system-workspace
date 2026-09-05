from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from assembly import build_system
from src.terminal import TerminalService


def _config(tmpdir: str) -> dict:
    return {
        "project_name": "Structural Deformation Research System",
        "series_ids": ["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"],
        "history_start": "2026-01-01",
        "mock_seed": 42,
        "thresholds": {"sigma": 99.0},
        "data": {"root": tmpdir, "version": "terminal-test"},
        "ode_params": {"dt": 1.0, "horizon": 2},
        "output": {"dir": tmpdir, "export_image": False},
        "event_log": {"path": str(Path(tmpdir) / "event_log.jsonl")},
        "text_log": {"path": str(Path(tmpdir) / "texts.jsonl")},
        "ml": {"enabled": False},
        "data_sources": {"enabled": ["fred"], "composite_max_workers": 2},
        "operators": {"enabled": True, "lookback_days": 30, "max_events": 5},
    }


class TerminalServiceTests(unittest.TestCase):
    def test_service_exposes_runtime_and_snapshot_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = build_system(_config(tmpdir), use_mock=True)
            service = TerminalService(
                pipeline=pipeline,
                snapshot_store=pipeline.snapshot_store,
                data_source=pipeline.data_source,
                config=_config(tmpdir),
            )

            health = service.health()
            runtime = service.runtime()
            snapshot = service.run_snapshot("2026-04-20", "WEEKLY")
            listed = service.list_snapshots("2026-04-01", "2026-04-30")
            fetched = service.get_snapshot("2026-04-20")

            self.assertEqual(health["status"], "ok")
            self.assertEqual(runtime["operators"]["match_cache"], True)
            self.assertEqual(snapshot["run_date"], "2026-04-20")
            self.assertEqual(len(listed), 1)
            self.assertIsNotNone(fetched)

    def test_service_fetch_data_returns_json_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = build_system(_config(tmpdir), use_mock=True)
            service = TerminalService(
                pipeline=pipeline,
                snapshot_store=pipeline.snapshot_store,
                data_source=pipeline.data_source,
                config=_config(tmpdir),
            )

            payload = service.fetch_data(["M_PROXY"], "2026-01-01", "2026-01-15")

            self.assertEqual(payload["columns"], ["M_PROXY"])
            self.assertGreaterEqual(len(payload["rows"]), 1)
            self.assertIn("date", payload["rows"][0])


if __name__ == "__main__":
    unittest.main()
