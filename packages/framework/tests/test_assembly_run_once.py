from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from assembly import _load_config, run_once


class AssemblyRunOnceTests(unittest.TestCase):
    def test_run_once_writes_html_and_json(self) -> None:
        cfg = _load_config("config.yaml")
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg["output"] = {
                "dir": tmpdir,
                "export_image": False,
                "image_width": 1000,
            }
            cfg["data"] = {"root": tmpdir, "version": "test-run-once"}
            snapshot, artifacts = run_once(cfg, run_date="2026-04-20", run_type="WEEKLY", use_mock=True)
            self.assertEqual(snapshot.run_date, "2026-04-20")
            self.assertIn("html", artifacts)
            self.assertIn("json", artifacts)
            self.assertTrue(Path(artifacts["html"]).exists())
            self.assertTrue(Path(artifacts["json"]).exists())


if __name__ == "__main__":
    unittest.main()
