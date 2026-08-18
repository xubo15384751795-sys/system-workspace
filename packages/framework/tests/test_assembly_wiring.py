from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from assembly import build_system
from src.core.interfaces import SnapshotStoreInterface
from src.data.harvester_snapshot_store import HarvesterSnapshotStore
from src.runtime.assembly import _build_snapshot_store


class AssemblyWiringTests(unittest.TestCase):
    def _base_config(self, output_dir: str, event_path: str, text_path: str) -> dict:
        return {
            "series_ids": ["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"],
            "history_start": "2026-01-01",
            "mock_seed": 42,
            "thresholds": {"sigma": 2.0},
            "data": {"root": output_dir, "version": "test-v1"},
            "ode_params": {"dt": 1.0, "horizon": 4},
            "output": {"dir": output_dir, "export_image": False, "image_width": 1200},
            "event_log": {"path": event_path},
            "text_log": {"path": text_path},
            "ml": {"enabled": False},
        }

    def test_build_system_uses_harvester_snapshot_store_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = self._base_config(
                output_dir=tmpdir,
                event_path=str(Path(tmpdir) / "event_log.jsonl"),
                text_path=str(Path(tmpdir) / "texts.jsonl"),
            )
            pipeline = build_system(cfg, use_mock=True)
            self.assertIsInstance(pipeline.snapshot_store, SnapshotStoreInterface)
            self.assertIsInstance(pipeline.snapshot_store, HarvesterSnapshotStore)
            self.assertEqual(pipeline.snapshot_store.root, Path(tmpdir) / "harvester" / "snapshots")

    def test_build_system_wires_event_and_text_loaders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / "event_log.jsonl"
            text_path = Path(tmpdir) / "texts.jsonl"

            event_path.write_text(
                json.dumps(
                    {
                        "date": "2026-04-16",
                        "actor": "REGULATOR",
                        "intervention_type": "capital rule",
                        "expected_direction": "IMPROVING",
                        "affected_proxy": ["D"],
                        "description": "Rule change.",
                        "created_at": "2026-04-16T00:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            text_path.write_text(
                json.dumps({"date": "2026-04-16", "text": "policy intervention and spread compression"}) + "\n",
                encoding="utf-8",
            )

            cfg = self._base_config(
                output_dir=tmpdir,
                event_path=str(event_path),
                text_path=str(text_path),
            )
            pipeline = build_system(cfg, use_mock=True)
            event_df = pipeline._load_event_log()
            texts = pipeline._load_recent_texts("2026-04-16")

            self.assertEqual(len(event_df), 1)
            self.assertEqual(event_df.iloc[0]["actor"], "REGULATOR")
            self.assertEqual(len(texts), 1)
            self.assertEqual(texts[0]["text"], "policy intervention and spread compression")

    def test_unknown_snapshot_backend_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "unsupported snapshot_store.backend"):
                _build_snapshot_store(
                    {
                        "data": {"root": tmpdir},
                        "snapshot_store": {"backend": "typo"},
                    }
                )


if __name__ == "__main__":
    unittest.main()
