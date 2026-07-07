from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ui.helpers.ui_runtime import JsonlEventLogger


class EventLoggerTests(unittest.TestCase):
    def test_write_and_load_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = JsonlEventLogger(Path(tmpdir) / "event_log.jsonl")
            logger.write_event(
                {
                    "date": "2026-04-14",
                    "actor": "CENTRAL_BANK",
                    "intervention_type": "Liquidity facility",
                    "expected_direction": "IMPROVING",
                    "affected_proxy": ["D", "K"],
                    "description": "Injected short-term liquidity.",
                    "created_at": "2026-04-14T00:00:00Z",
                }
            )
            loaded = logger.load_events()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded.iloc[0]["actor"], "CENTRAL_BANK")
            self.assertEqual(loaded.iloc[0]["affected_proxy"], "D,K")


if __name__ == "__main__":
    unittest.main()
