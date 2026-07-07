from __future__ import annotations

import unittest

import pandas as pd

from src.ui.components.research_log_panel import build_reflexivity_tracker


class ReflexivityTrackerTests(unittest.TestCase):
    def test_build_reflexivity_tracker_adds_direction_columns(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "date": "2026-01-01",
                    "actor": "VC_FUND",
                    "intervention_type": "Risk-on deployment",
                    "expected_direction": "IMPROVING",
                    "affected_proxy": "M,X",
                    "description": "Capital injection in growth sectors.",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        )
        history = pd.DataFrame(
            [
                {"date": "2026-01-01", "M": 0.2, "D": 0.1, "K": 0.1, "X": 0.2},
                {"date": "2026-02-01", "M": 0.4, "D": 0.2, "K": 0.2, "X": 0.5},
                {"date": "2026-03-05", "M": 0.5, "D": 0.3, "K": 0.4, "X": 0.6},
            ]
        )
        tracker = build_reflexivity_tracker(events, history)
        self.assertIn("t30_direction", tracker.columns)
        self.assertIn("t60_direction", tracker.columns)
        self.assertIn("reflexivity_active", tracker.columns)
        self.assertEqual(len(tracker), 1)


if __name__ == "__main__":
    unittest.main()
