"""OBS-1 / OBS-2: observation integrity models, serialization, and series metrics."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

import numpy as np
import pandas as pd

from src.dynamic.integrity_series_metrics import (
    compute_event_window_variance,
    compute_forward_fill_ratio,
    compute_missingness_ratio,
    compute_staleness_score,
)
from src.dynamic.observation_integrity import ObservationIntegrity, ProviderIntegrityCheck


def _sample_check(**overrides: object) -> ProviderIntegrityCheck:
    base = ProviderIntegrityCheck(
        logical_series="m",
        provider="p1",
        status="pass",
        frequency="daily",
        required_resolution="daily",
        missingness_ratio=0.1,
        forward_fill_ratio=None,
        event_window_variance=0.5,
        staleness_score=0.2,
        provider_disagreement=None,
        fallback_used=False,
        mock_used=False,
        issues=[],
        interpretation="ok",
    )
    return replace(base, **overrides)


class TestProviderIntegrityCheckValidation(unittest.TestCase):
    def test_invalid_status(self) -> None:
        with self.assertRaises(ValueError):
            _sample_check(status="bad")

    def test_ratio_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            _sample_check(missingness_ratio=1.1)

    def test_negative_variance(self) -> None:
        with self.assertRaises(ValueError):
            _sample_check(event_window_variance=-0.01)


class TestObservationIntegrityValidation(unittest.TestCase):
    def test_invalid_overall_status(self) -> None:
        with self.assertRaises(ValueError):
            ObservationIntegrity(
                case_id="c",
                overall_status="nope",
                checks=[_sample_check()],
                static_source_risk=None,
                provider_disagreement_available=False,
                summary="s",
            )

    def test_diagnostic_only_must_be_true(self) -> None:
        with self.assertRaises(ValueError):
            ObservationIntegrity(
                case_id=None,
                overall_status="unknown",
                checks=[],
                static_source_risk=None,
                provider_disagreement_available=False,
                summary="s",
                diagnostic_only=False,  # type: ignore[arg-type]
            )


class TestSerialization(unittest.TestCase):
    def test_round_trip_json_safe(self) -> None:
        obs = ObservationIntegrity(
            case_id="ld_2022",
            overall_status="medium",
            checks=[_sample_check(logical_series="credit", issues=["stale"])],
            static_source_risk=None,
            provider_disagreement_available=True,
            summary="Mixed signals.",
        )
        d = obs.to_serializable_dict()
        json.dumps(d)
        self.assertTrue(d["diagnostic_only"])
        self.assertEqual(len(d["checks"]), 1)
        self.assertEqual(d["checks"][0]["logical_series"], "credit")


class TestComputeMissingnessRatio(unittest.TestCase):
    def test_basic(self) -> None:
        s = pd.Series([1.0, float("nan"), 3.0])
        self.assertAlmostEqual(compute_missingness_ratio(s), 1.0 / 3.0)

    def test_empty_is_all_missing(self) -> None:
        self.assertEqual(compute_missingness_ratio(pd.Series([], dtype=float)), 1.0)


class TestComputeEventWindowVariance(unittest.TestCase):
    def test_full_series(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 4.0])
        v = compute_event_window_variance(s)
        assert v is not None
        self.assertAlmostEqual(v, 1.25)

    def test_datetime_window(self) -> None:
        idx = pd.date_range("2024-01-01", periods=5, freq="D")
        s = pd.Series([1.0, 1.0, 10.0, 10.0, 10.0], index=idx)
        v = compute_event_window_variance(s, start="2024-01-03", end="2024-01-05")
        assert v is not None
        self.assertAlmostEqual(v, 0.0)

    def test_insufficient_points_returns_none(self) -> None:
        s = pd.Series([1.0])
        self.assertIsNone(compute_event_window_variance(s))


class TestStalenessScore(unittest.TestCase):
    def test_flat_series_high_staleness(self) -> None:
        idx = pd.date_range("2024-01-01", periods=20, freq="D")
        flat = pd.Series([1.0] * 20, index=idx)
        volatile = pd.Series(np.linspace(0, 50, 20), index=idx)

        s_flat = compute_staleness_score(flat)
        s_vol = compute_staleness_score(volatile)
        self.assertGreater(s_flat, s_vol)

    def test_volatile_lower_than_flat(self) -> None:
        idx = pd.date_range("2024-01-01", periods=30, freq="D")
        flat = pd.Series([2.0] * 30, index=idx)
        rng = pd.Series(range(30), dtype=float, index=idx)
        self.assertGreater(compute_staleness_score(flat), compute_staleness_score(rng))


class TestForwardFillRatio(unittest.TestCase):
    def test_none_without_metadata(self) -> None:
        s = pd.Series([1.0, 1.0, 1.0])
        self.assertIsNone(compute_forward_fill_ratio(s, metadata=None))

    def test_explicit_metadata(self) -> None:
        s = pd.Series([1.0, 2.0])
        r = compute_forward_fill_ratio(s, metadata={"forward_fill_ratio": 0.25})
        self.assertAlmostEqual(r, 0.25)

    def test_forward_fill_count_metadata(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0])
        r = compute_forward_fill_ratio(
            s,
            metadata={"forward_fill_count": 3.0, "series_length": 12.0},
        )
        self.assertAlmostEqual(r, 0.25)


class TestMetricsDoNotMutateInput(unittest.TestCase):
    def test_series_unchanged(self) -> None:
        idx = pd.date_range("2024-01-01", periods=5, freq="D")
        original = pd.Series([1.0, float("nan"), 3.0, 4.0, 5.0], index=idx)
        backup = original.copy(deep=True)
        _ = compute_missingness_ratio(original)
        _ = compute_event_window_variance(original, start="2024-01-02", end="2024-01-04")
        _ = compute_staleness_score(original)
        _ = compute_forward_fill_ratio(original, metadata={"forward_fill_ratio": 0.1})
        pd.testing.assert_series_equal(original, backup)


if __name__ == "__main__":
    unittest.main()
