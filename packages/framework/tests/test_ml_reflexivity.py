from __future__ import annotations

import unittest

import pandas as pd

from src.ml.ml_reflexivity import DTWReflexivityDetector


class MLReflexivityTests(unittest.TestCase):
    def test_check_returns_channel_flags(self) -> None:
        detector = DTWReflexivityDetector(channel_threshold=0.2)
        proxy_history = pd.DataFrame(
            [
                {"date": "2026-04-01", "M": 0.1, "D": 0.2, "K": 0.3, "X": 0.4},
                {"date": "2026-04-08", "M": 0.5, "D": 0.6, "K": 0.8, "X": 0.7},
                {"date": "2026-04-15", "M": 0.9, "D": 1.0, "K": 1.1, "X": 1.2},
            ]
        ).set_index("date")
        event_log = pd.DataFrame(
            [
                {"date": "2026-04-10", "channel": "policy", "event": "statement"},
                {"date": "2026-04-12", "channel": "policy", "event": "facility"},
            ]
        )

        flags = detector.check(event_log=event_log, proxy_history=proxy_history, run_date="2026-04-15")
        self.assertEqual(set(flags.keys()), {"credit", "liquidity", "policy"})
        self.assertTrue(all(isinstance(v, bool) for v in flags.values()))


if __name__ == "__main__":
    unittest.main()
