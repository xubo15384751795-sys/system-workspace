from __future__ import annotations

import unittest

import pandas as pd

from src.derivation.graph_engine import GraphEngine, coupling_band, coupling_code


class GraphEngineTests(unittest.TestCase):
    def test_coupling_band_thresholds_are_discrete(self) -> None:
        self.assertEqual(coupling_band(-0.8), "Inverse Coupling")
        self.assertEqual(coupling_band(-0.4), "Tension")
        self.assertEqual(coupling_band(0.0), "Decoupled")
        self.assertEqual(coupling_band(0.4), "Coupled")
        self.assertEqual(coupling_band(0.8), "Synchronized")

    def test_coupling_codes_preserve_proxy_matrix_shape(self) -> None:
        history = pd.DataFrame(
            {
                "M": [1.0, 2.0, 3.0, 4.0],
                "D": [4.0, 3.0, 2.0, 1.0],
                "K": [1.0, 1.5, 2.0, 2.5],
                "X": [2.0, 2.0, 2.0, 2.0],
            }
        )

        codes = GraphEngine().coupling_codes(history)

        self.assertEqual(list(codes.index), ["M", "D", "K", "X"])
        self.assertEqual(list(codes.columns), ["M", "D", "K", "X"])
        self.assertEqual(codes.loc["M", "D"], -2)
        self.assertEqual(codes.loc["M", "M"], 0)

    def test_self_channel_is_labeled_as_reference_not_coupling(self) -> None:
        history = pd.DataFrame(
            {
                "M": [1.0, 2.0, 3.0, 4.0],
                "D": [4.0, 3.0, 2.0, 1.0],
                "K": [1.0, 1.5, 2.0, 2.5],
                "X": [2.0, 2.5, 2.0, 2.5],
            }
        )

        bands = GraphEngine().coupling_bands(history)

        self.assertEqual(bands.loc["D", "D"], "Self")
        self.assertEqual(coupling_code("Self"), 0)


if __name__ == "__main__":
    unittest.main()
