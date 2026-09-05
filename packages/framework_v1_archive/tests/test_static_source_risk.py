"""OBS-3: static-source risk detection (diagnostic-only)."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.dynamic.static_source_risk import detect_static_source_risk


def _default_kwargs() -> dict[str, object]:
    return {
        "logical_series": "credit_spread",
        "provider": "fred",
        "frequency": "daily",
        "required_resolution": "daily",
        "fallback_used": False,
        "mock_used": False,
    }


class TestStaticSourceRiskHighStressFlat(unittest.TestCase):
    def test_high_stress_flat_adds_static_source_risk(self) -> None:
        idx = pd.date_range("2024-01-01", periods=25, freq="D")
        s = pd.Series([1.0] * 25, index=idx)
        r = detect_static_source_risk(
            s,
            event_window=None,
            high_stress=True,
            **_default_kwargs(),  # type: ignore[arg-type]
        )
        self.assertIn("static_source_risk", r.issues)
        self.assertEqual(r.status, "warn")

    def test_non_high_stress_flat_does_not_fail(self) -> None:
        idx = pd.date_range("2024-01-01", periods=25, freq="D")
        s = pd.Series([1.0] * 25, index=idx)
        r = detect_static_source_risk(
            s,
            event_window=None,
            high_stress=False,
            **_default_kwargs(),  # type: ignore[arg-type]
        )
        self.assertNotIn("static_source_risk", r.issues)
        self.assertNotEqual(r.status, "fail")


class TestStaticSourceMissingness(unittest.TestCase):
    def test_severe_missingness_fails(self) -> None:
        idx = pd.date_range("2024-01-01", periods=10, freq="D")
        s = pd.Series([float("nan")] * 8 + [1.0, 2.0], index=idx)
        r = detect_static_source_risk(
            s,
            event_window=None,
            high_stress=False,
            **_default_kwargs(),  # type: ignore[arg-type]
        )
        self.assertIn("high_missingness", r.issues)
        self.assertEqual(r.status, "fail")

    def test_material_missingness_warns(self) -> None:
        idx = pd.date_range("2024-01-01", periods=10, freq="D")
        vals = [1.0, 2.0, 3.0, 4.0, float("nan"), float("nan"), float("nan"), float("nan"), 5.0, 6.0]
        s = pd.Series(vals, index=idx)
        r = detect_static_source_risk(
            s,
            event_window=None,
            high_stress=False,
            **_default_kwargs(),  # type: ignore[arg-type]
        )
        self.assertIn("high_missingness", r.issues)
        self.assertEqual(r.status, "warn")


class TestResolutionMismatch(unittest.TestCase):
    def test_weekly_below_daily_requirement(self) -> None:
        idx = pd.date_range("2024-01-01", periods=20, freq="D")
        s = pd.Series(np.linspace(0, 1, 20), index=idx)
        r = detect_static_source_risk(
            s,
            event_window=None,
            high_stress=False,
            logical_series="x",
            provider="p",
            frequency="weekly",
            required_resolution="daily",
            fallback_used=False,
            mock_used=False,
        )
        self.assertIn("resolution_below_event_requirement", r.issues)
        self.assertEqual(r.status, "warn")


class TestFallbackUsed(unittest.TestCase):
    def test_fallback_adds_issue_watch_when_only_minor(self) -> None:
        idx = pd.date_range("2024-01-01", periods=15, freq="D")
        s = pd.Series(np.linspace(0, 5, 15), index=idx)
        r = detect_static_source_risk(
            s,
            event_window=None,
            high_stress=False,
            logical_series="x",
            provider=None,
            frequency="daily",
            required_resolution="daily",
            fallback_used=True,
            mock_used=False,
        )
        self.assertIn("fallback_used", r.issues)
        self.assertEqual(r.status, "watch")


class TestMockUsed(unittest.TestCase):
    def test_mock_triggers_fail(self) -> None:
        idx = pd.date_range("2024-01-01", periods=15, freq="D")
        s = pd.Series(np.linspace(0, 3, 15), index=idx)
        r = detect_static_source_risk(
            s,
            event_window=None,
            high_stress=False,
            logical_series="x",
            provider=None,
            frequency="daily",
            required_resolution="daily",
            mock_used=True,
        )
        self.assertEqual(r.status, "fail")


class TestNoInputMutation(unittest.TestCase):
    def test_series_unchanged(self) -> None:
        idx = pd.date_range("2024-01-01", periods=12, freq="D")
        original = pd.Series([1.0, float("nan")] + [2.0] * 10, index=idx)
        backup = original.copy(deep=True)
        _ = detect_static_source_risk(
            original,
            event_window=("2024-01-03", "2024-01-10"),
            high_stress=True,
            **_default_kwargs(),  # type: ignore[arg-type]
        )
        pd.testing.assert_series_equal(original, backup)


if __name__ == "__main__":
    unittest.main()
