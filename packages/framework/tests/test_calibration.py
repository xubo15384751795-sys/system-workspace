from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from src.core.calibration import build_proxy_weights, build_thresholds


class CalibrationTests(unittest.TestCase):
    def test_thresholds_are_frozen(self) -> None:
        cfg = {"thresholds": {"sigma": 1.5}}
        thresholds = build_thresholds(cfg)
        self.assertEqual(thresholds.sigma, 1.5)
        self.assertEqual(thresholds.calibration_mode, "fixed_config")
        self.assertTrue(thresholds.frozen)
        with self.assertRaises(FrozenInstanceError):
            thresholds.sigma = 2.0  # type: ignore[misc]

    def test_threshold_protocol_records_train_eval_windows(self) -> None:
        cfg = {
            "thresholds": {
                "protocol": {
                    "calibration_mode": "train_eval_split",
                    "training_window": {"start": "2020-01-01", "end": "2021-12-31"},
                    "evaluation_window": ["2022-01-01", "2023-12-31"],
                    "frozen": True,
                }
            }
        }
        thresholds = build_thresholds(cfg)
        self.assertEqual(thresholds.calibration_mode, "train_eval_split")
        self.assertEqual(thresholds.training_window, ("2020-01-01", "2021-12-31"))
        self.assertEqual(thresholds.evaluation_window, ("2022-01-01", "2023-12-31"))

    def test_proxy_weights_are_frozen(self) -> None:
        cfg = {"proxies": {"weights": {"M": 0.4, "D": 0.3, "K": 0.2, "X": 0.1}}}
        weights = build_proxy_weights(cfg)
        self.assertAlmostEqual(weights.M, 0.4)
        with self.assertRaises(FrozenInstanceError):
            weights.M = 0.5  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
