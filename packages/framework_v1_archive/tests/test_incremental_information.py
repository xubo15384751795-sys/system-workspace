from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.research.incremental_information import (
    IncrementalInformationReport,
    information_regression,
    mechanism_specificity,
    out_of_sample_forecast,
    regime_lead_lag,
)


def _toy_data(n: int = 600, seed: int = 11) -> tuple[pd.Series, pd.Series, dict[str, pd.Series]]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-01", periods=n, freq="W-FRI")
    nfci = pd.Series(rng.normal(0.0, 1.0, n).cumsum() * 0.05, index=idx, name="NFCI")
    kcfsi = pd.Series(rng.normal(0.0, 1.0, n).cumsum() * 0.05, index=idx, name="KCFSI")
    # Sigma: partly redundant with NFCI but adds an independent component
    sigma = pd.Series(0.6 * nfci + 0.4 * rng.normal(0.0, 1.0, n), index=idx, name="SIGMA")
    # Target: future stress driven by sigma + nfci
    target = pd.Series(
        0.5 * sigma.shift(-5).fillna(0.0) + 0.3 * nfci + rng.normal(0.0, 0.5, n),
        index=idx,
        name="TARGET",
    )
    return target, sigma, {"NFCI": nfci, "KCFSI": kcfsi}


class InformationRegressionTests(unittest.TestCase):
    def test_information_regression_finds_signal_coefficient(self) -> None:
        target, sigma, controls = _toy_data()
        result = information_regression(
            target=target,
            signal=sigma,
            controls=controls,
            horizon=10,
            signal_name="SIGMA",
        )
        self.assertGreater(result.n_obs, 100)
        sigma_term = result.signal_term("SIGMA")
        self.assertIsNotNone(sigma_term)
        self.assertGreater(abs(sigma_term.t_stat), 0.5)
        self.assertGreaterEqual(result.r_squared, result.r_squared_controls_only - 1e-6)
        self.assertGreaterEqual(result.r_squared, 0.0)
        self.assertLessEqual(result.r_squared, 1.0)

    def test_information_regression_handles_short_series(self) -> None:
        idx = pd.date_range("2024-01-01", periods=8, freq="W-FRI")
        target = pd.Series(np.arange(8.0), index=idx, name="T")
        signal = pd.Series(np.arange(8.0) * 0.5, index=idx, name="SIGMA")
        controls = {"NFCI": pd.Series(np.zeros(8), index=idx, name="NFCI")}
        result = information_regression(target, signal, controls, horizon=20, signal_name="SIGMA")
        self.assertEqual(result.terms, tuple())


class OOSForecastTests(unittest.TestCase):
    def test_oos_forecast_runs_three_models(self) -> None:
        target, sigma, controls = _toy_data(n=800)
        result = out_of_sample_forecast(
            target=target,
            signal=sigma,
            controls=controls,
            horizon=5,
            train_end="2018-12-31",
            eval_start="2019-01-01",
        )
        self.assertEqual(set(result.metrics_per_model.keys()), {"signal_only", "controls_only", "signal_plus_controls"})
        self.assertGreater(result.n_train, 50)
        self.assertGreater(result.n_eval, 20)
        self.assertIn(result.winner, result.metrics_per_model)

    def test_binary_threshold_uses_brier(self) -> None:
        target, sigma, controls = _toy_data(n=800)
        result = out_of_sample_forecast(
            target=target,
            signal=sigma,
            controls=controls,
            horizon=5,
            train_end="2018-12-31",
            eval_start="2019-01-01",
            binary_threshold=float(target.quantile(0.85)),
        )
        for label, metrics in result.metrics_per_model.items():
            self.assertIn("brier", metrics, label)


class RegimeLeadLagTests(unittest.TestCase):
    def test_regime_lead_lag_reports_peak_lag(self) -> None:
        idx = pd.date_range("2010-01-01", periods=400, freq="B")
        regime = pd.Series(0, index=idx)
        regime.iloc[100:120] = 1
        regime.iloc[250:270] = 1
        signal = pd.Series(0.0, index=idx)
        signal.iloc[95:120] = 1.5
        signal.iloc[245:270] = 1.5
        result = regime_lead_lag(signal.rename("SIGMA"), regime.rename("REGIME"), max_lag=20)
        self.assertGreater(result.best_correlation, 0.3)
        self.assertEqual(result.n_regimes, 2)


class MechanismSpecificityTests(unittest.TestCase):
    def test_mechanism_specificity_picks_dominant_channel(self) -> None:
        idx = pd.date_range("2020-01-01", periods=120, freq="B")
        channels = pd.DataFrame({
            "M": np.zeros(120),
            "D": np.zeros(120),
            "K": np.linspace(0.0, 2.0, 120),
            "X": np.linspace(0.0, 0.4, 120),
        }, index=idx)
        sigma = pd.Series(np.linspace(0.0, 1.0, 120), index=idx, name="SIGMA")
        result = mechanism_specificity(
            case_name="synthetic_curvature",
            channels=channels,
            sigma=sigma,
            window_start="2020-01-01",
            window_end="2020-06-30",
            expected_channel="K",
        )
        self.assertEqual(result.observed_leading_channel, "K")
        self.assertTrue(result.matches_expectation)
        self.assertGreater(result.leading_channel_share, 0.5)


class IncrementalReportTests(unittest.TestCase):
    def test_summary_frame_combines_all_tests(self) -> None:
        target, sigma, controls = _toy_data(n=500)
        ra = information_regression(target, sigma, controls, horizon=5, signal_name="SIGMA")
        rb = out_of_sample_forecast(
            target=target,
            signal=sigma,
            controls=controls,
            horizon=5,
            train_end="2017-12-31",
            eval_start="2018-01-01",
        )
        regime = (target > target.quantile(0.85)).astype(int).rename("HIGH")
        rc = regime_lead_lag(sigma, regime, max_lag=10)
        idx = pd.date_range("2010-01-01", periods=120, freq="B")
        channels = pd.DataFrame({
            "M": np.linspace(0, 1, 120),
            "D": np.linspace(0, -0.5, 120),
            "K": np.linspace(0, 0.3, 120),
            "X": np.linspace(0, 0.2, 120),
        }, index=idx)
        rd = mechanism_specificity("synthetic_M", channels, sigma.reindex(idx, method="ffill"),
                                   "2010-01-01", "2010-06-30", expected_channel="M")
        report = IncrementalInformationReport((ra,), (rb,), (rc,), (rd,))
        df = report.to_summary_frame()
        self.assertEqual(set(df["test"]), {
            "A_information_regression",
            "B_oos_forecast",
            "C_regime_lead_lag",
            "D_mechanism_specificity",
        })


if __name__ == "__main__":
    unittest.main()
