from __future__ import annotations

import unittest

from src.ml.ml_narrative import SentenceTransformerDetector


class MLNarrativeTests(unittest.TestCase):
    def test_analyze_returns_narrative_reading(self) -> None:
        texts = [
            {"date": "2026-04-01", "source": "news", "text": "Fed policy tightening and intervention signals"},
            {"date": "2026-04-01", "source": "blog", "text": "AI unicorn valuation drift and burn concerns"},
        ]
        detector = SentenceTransformerDetector()
        reading = detector.analyze(texts, run_date="2026-04-14")

        self.assertEqual(reading.run_date, "2026-04-14")
        self.assertIn(reading.ai_unicorn, {"ANCHORED", "DRIFTING", "COMPRESSION_ILLUSION"})
        self.assertIn(reading.policy, {"ANCHORED", "DRIFTING", "COMPRESSION_ILLUSION"})
        self.assertIn("ai_unicorn", reading.drift_scores)


if __name__ == "__main__":
    unittest.main()
