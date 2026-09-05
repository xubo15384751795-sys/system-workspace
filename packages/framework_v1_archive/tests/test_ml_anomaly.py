from __future__ import annotations

import unittest

from src._legacy.data.data_sources import MockDataSource
from src.ml.ml_anomaly import IsolationForestDetector
from src.derivation.proxy_builder import DefaultProxyBuilder


class MLAnomalyTests(unittest.TestCase):
    def test_score_returns_float_with_mock_proxy(self) -> None:
        raw = MockDataSource(seed=31).fetch(["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"], "2026-01-01", "2026-02-01")
        proxy = DefaultProxyBuilder().build(raw, "2026-02-01")

        score = IsolationForestDetector().score(proxy)
        self.assertIsInstance(score, float)


if __name__ == "__main__":
    unittest.main()
