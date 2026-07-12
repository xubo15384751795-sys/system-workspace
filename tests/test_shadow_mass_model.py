"""Tests for the nonlinear-framework shadow maturity-mass model."""
from __future__ import annotations

import numpy as np

from scripts.shadow_mass_model import (
    ShadowMassParams,
    filter_shadow_mass,
    fit_shadow_mass_mle,
    rate_vector,
    simulate_shadow_mass,
)


def _truth() -> ShadowMassParams:
    return ShadowMassParams(
        lambda_r=0.3,
        eta=0.2,
        rho0=0.05,
        rho_d=0.4,
        rho_k=0.35,
        rho_xi=0.0,
        kappa=0.05,
        sigma_x=0.02,
        sigma_y=0.05,
    )


def test_synthetic_recovery_with_identification_anchors() -> None:
    """Recover stress loadings with rho_xi/kappa and nuisance anchors fixed.

    lambda_r and rho_* enter A_t as products, so the synthetic G2 gate fixes
    rho0/eta/noise in addition to rho_xi=0 and kappa at truth.
    """
    rng = np.random.default_rng(42)
    n = 500
    params = _truth()
    weeks = np.arange(n)
    m = rng.gamma(shape=2.0, scale=0.08, size=n)
    d_stress = np.clip(
        0.40 + 0.30 * np.sin(weeks / 17.0) + rng.normal(0.0, 0.035, n),
        0.0,
        None,
    )
    k_stress = np.clip(
        0.35 + 0.25 * np.cos(weeks / 23.0) + rng.normal(0.0, 0.035, n),
        0.0,
        None,
    )
    sim = simulate_shadow_mass(m, d_stress, k_stress, params, seed=43)
    fit = fit_shadow_mass_mle(
        sim["y"],
        m,
        d_stress,
        k_stress,
        initial_params=ShadowMassParams(
            lambda_r=0.25,
            eta=params.eta,
            rho0=params.rho0,
            rho_d=0.30,
            rho_k=0.30,
            rho_xi=0.0,
            kappa=params.kappa,
            sigma_x=params.sigma_x,
            sigma_y=params.sigma_y,
        ),
        fixed_params={
            "eta": params.eta,
            "rho0": params.rho0,
            "rho_xi": 0.0,
            "kappa": params.kappa,
            "sigma_x": params.sigma_x,
            "sigma_y": params.sigma_y,
        },
        maxiter=80,
    )

    assert abs(fit.lambda_r - params.lambda_r) / params.lambda_r < 0.30
    assert abs(fit.rho_d - params.rho_d) / params.rho_d < 0.30
    assert abs(fit.rho_k - params.rho_k) / params.rho_k < 0.30


def test_mass_conservation_without_release_transport_or_injection() -> None:
    params = ShadowMassParams(
        lambda_r=0.0,
        eta=0.2,
        rho0=0.0,
        rho_d=0.0,
        rho_k=0.0,
        rho_xi=0.0,
        kappa=0.0,
        sigma_x=0.0,
        sigma_y=0.0,
    )
    n = 80
    x0 = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    sim = simulate_shadow_mass(
        np.zeros(n),
        np.zeros(n),
        np.zeros(n),
        params,
        x0=x0,
        seed=1,
    )

    assert np.allclose(sim["X"].sum(axis=1), x0.sum(), atol=1e-5)
    assert np.allclose(sim["release_flow"], 0.0, atol=1e-12)


def test_filtered_state_is_non_negative_for_sensible_positive_path() -> None:
    rng = np.random.default_rng(3)
    n = 120
    params = _truth()
    m = rng.gamma(shape=2.0, scale=0.08, size=n)
    d_stress = rng.uniform(0.0, 0.7, size=n)
    k_stress = rng.uniform(0.0, 0.6, size=n)
    sim = simulate_shadow_mass(m, d_stress, k_stress, params, seed=4)

    filtered = filter_shadow_mass(sim["y"], m, d_stress, k_stress, params)
    bucket_cols = [f"x_bucket_{j}" for j in range(5)]

    assert (filtered[bucket_cols].to_numpy() >= -1e-12).all()
    assert filtered["short_share"].between(0.0, 1.0).all()


def test_release_flow_increases_with_d_or_k_stress() -> None:
    params = _truth()
    fixed_x = np.array([3.0, 2.0, 1.5, 1.0, 0.5])

    low = np.sum(params.lambda_r * rate_vector(0.1, 0.1, params) * fixed_x)
    high_d = np.sum(params.lambda_r * rate_vector(0.8, 0.1, params) * fixed_x)
    high_k = np.sum(params.lambda_r * rate_vector(0.1, 0.8, params) * fixed_x)

    assert high_d > low
    assert high_k > low
