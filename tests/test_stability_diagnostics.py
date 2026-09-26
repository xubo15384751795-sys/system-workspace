from __future__ import annotations

import numpy as np
import pandas as pd
from workbench.measurement.stability_diagnostics import (
    build_stability_candidates,
    critical_slowing_score,
    rls_var_lambda_max,
    rolling_var_lambda_max,
)


def _var_panel(coef: np.ndarray, n: int = 900, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    values = np.zeros((n, coef.shape[0]))
    noise = rng.normal(0.0, 0.05, size=values.shape)
    for t in range(1, n):
        values[t] = coef @ values[t - 1] + noise[t]
    return pd.DataFrame(values, columns=["M", "D_contraction", "K", "x_stock_agg"])


def test_rolling_var_estimates_known_spectral_radius_within_ten_percent() -> None:
    coef = np.array(
        [
            [0.70, 0.04, 0.00, 0.00],
            [0.00, 0.55, 0.03, 0.00],
            [0.00, 0.00, 0.45, 0.02],
            [0.00, 0.00, 0.00, 0.30],
        ]
    )
    panel = _var_panel(coef)
    estimate = rolling_var_lambda_max(panel, window=500, step=10).dropna().iloc[-1]
    assert abs(float(estimate) - 0.70) / 0.70 < 0.10


def test_simulated_instability_path_lambda_max_rises() -> None:
    rng = np.random.default_rng(1)
    n = 900
    values = np.zeros((n, 4))
    for t in range(1, n):
        rho = 0.35 if t < 450 else 0.85
        values[t] = rho * values[t - 1] + rng.normal(0.0, 0.05, 4)
    panel = pd.DataFrame(values, columns=["M", "D_contraction", "K", "x_stock_agg"])
    lam = rolling_var_lambda_max(panel, window=220, step=5)
    early = float(lam.iloc[300:430].mean())
    late = float(lam.iloc[700:850].mean())
    assert late > early + 0.25


def test_rls_and_csd_emit_probabilities_on_smooth_panel() -> None:
    panel = _var_panel(np.eye(4) * 0.65, n=500, seed=2)
    rls = rls_var_lambda_max(panel, forgetting=0.99)
    csd = critical_slowing_score(panel, window=80, long_window=160, min_periods=40)
    assert rls.dropna().notna().any()
    assert csd.dropna().between(0.0, 1.0).all()


def test_build_stability_candidates_smoke_with_noise_guard_columns() -> None:
    panel = _var_panel(np.eye(4) * 0.5, n=360, seed=3)
    result = build_stability_candidates(panel, window=120, step=10, bootstrap_reps=5, block_size=10)
    expected = {
        "lambda_max",
        "lambda_max_rls",
        "csd_score",
        "candidate_lambda_max_pit",
        "candidate_csd_score_pit",
        "lambda_ci_low",
        "lambda_ci_high",
        "lambda_q90",
        "lambda_noise_guard_signal",
    }
    assert expected.issubset(result.columns)
    assert result["lambda_max"].dropna().notna().any()
