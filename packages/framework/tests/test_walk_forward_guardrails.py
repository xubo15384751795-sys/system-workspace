from __future__ import annotations

import unittest

import pandas as pd

from src.validation.walk_forward import rolling_origin_oos_validate


class WalkForwardGuardrailTests(unittest.TestCase):
    def test_walk_forward_rejects_unsorted_signal_index(self) -> None:
        signal = pd.Series(
            [0.2, 0.1, 0.3],
            index=pd.to_datetime(["2026-01-02", "2026-01-01", "2026-01-03"]),
        )
        target = pd.Series(
            [False, True, False],
            index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
        )

        with self.assertRaisesRegex(ValueError, "future index leakage guard failed"):
            rolling_origin_oos_validate(signal, target)


if __name__ == "__main__":
    unittest.main()
