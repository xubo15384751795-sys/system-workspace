"""Shadow maturity-mass state model for the nonlinear framework research line."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

MATURITY_GRID = np.array([0.25, 1.0, 4.0, 8.5, 15.0], dtype=float)
N_BUCKETS = len(MATURITY_GRID)
LAMBDA_M = 1.0
_PARAM_NAMES = (
    "lambda_r",
    "eta",
    "rho0",
    "rho_d",
    "rho_k",
    "rho_xi",
    "kappa",
    "sigma_x",
    "sigma_y",
)


@dataclass(frozen=True)
class ShadowMassParams:
    lambda_r: float
    eta: float
    rho0: float
    rho_d: float
    rho_k: float
    rho_xi: float
    kappa: float
    sigma_x: float
    sigma_y: float
    # lambda_m is identified and fixed at 1.0.


def q_eta(eta: float, xi: np.ndarray | None = None) -> np.ndarray:
    """Softmax maturity injection weights, tilted short when eta is large."""
    grid = MATURITY_GRID if xi is None else np.asarray(xi, dtype=float)
    raw = -float(eta) * grid
    raw = raw - np.max(raw)
    weights = np.exp(raw)
    return weights / np.sum(weights)


def transport_laplacian(n_buckets: int = N_BUCKETS) -> np.ndarray:
    """Nearest-neighbor diffusion Laplacian with row sums equal to zero."""
    lap = np.zeros((n_buckets, n_buckets), dtype=float)
    for i in range(n_buckets):
        if i > 0:
            lap[i, i - 1] = 1.0
        if i < n_buckets - 1:
            lap[i, i + 1] = 1.0
        lap[i, i] = -np.sum(lap[i])
    return lap


def rate_vector(
    d_value: float,
    k_value: float,
    params: ShadowMassParams,
    xi: np.ndarray | None = None,
) -> np.ndarray:
    grid = MATURITY_GRID if xi is None else np.asarray(xi, dtype=float)
    return (
        float(params.rho0)
        + float(params.rho_d) * float(d_value)
        + float(params.rho_k) * float(k_value)
        + float(params.rho_xi) * grid
    )


def transition_matrix(
    d_value: float,
    k_value: float,
    params: ShadowMassParams,
    xi: np.ndarray | None = None,
) -> np.ndarray:
    rates = rate_vector(d_value, k_value, params, xi)
    return np.diag(1.0 - float(params.lambda_r) * rates) + float(params.kappa) * transport_laplacian(
        len(rates)
    )


def _as_1d(values: Any, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return arr


def _prepare_inputs(
    m: Any,
    d_stress: Any,
    k_stress: Any,
    obs: Any | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    m_arr = _as_1d(m, "m")
    d_arr = _as_1d(d_stress, "d_stress")
    k_arr = _as_1d(k_stress, "k_stress")
    lengths = {len(m_arr), len(d_arr), len(k_arr)}
    obs_arr = None
    if obs is not None:
        obs_arr = np.asarray(obs, dtype=float)
        if obs_arr.ndim == 1:
            obs_arr = obs_arr[:, None]
        if obs_arr.ndim != 2:
            raise ValueError("obs must be one- or two-dimensional")
        lengths.add(obs_arr.shape[0])
    if len(lengths) != 1:
        raise ValueError("m, d_stress, k_stress, and obs must have matching lengths")
    return m_arr, d_arr, k_arr, obs_arr


def _prepare_h(H: Any | None, n_obs: int | None = None) -> np.ndarray:
    if H is None:
        h = np.ones((1, N_BUCKETS), dtype=float)
    else:
        h = np.asarray(H, dtype=float)
        if h.ndim == 1:
            h = h[None, :]
        if h.ndim != 2 or h.shape[1] != N_BUCKETS:
            raise ValueError(f"H must have shape (n_obs, {N_BUCKETS})")
    if n_obs is not None and h.shape[0] != n_obs:
        raise ValueError("H row count must match obs columns")
    return h


def _positive_params(params: ShadowMassParams) -> ShadowMassParams:
    values = {
        name: max(float(getattr(params, name)), 0.0)
        for name in _PARAM_NAMES
    }
    values["sigma_x"] = max(values["sigma_x"], 1e-8)
    values["sigma_y"] = max(values["sigma_y"], 1e-8)
    return ShadowMassParams(**values)


def _default_initial_state(obs_arr: np.ndarray | None, params: ShadowMassParams) -> np.ndarray:
    weights = q_eta(params.eta)
    if obs_arr is not None and obs_arr.size:
        finite = obs_arr[np.isfinite(obs_arr)]
        total = float(finite[0]) if finite.size else 1.0
    else:
        total = 1.0
    return weights * max(total, 1e-6)


def _release_flow_for_state(
    state: np.ndarray,
    d_value: float,
    k_value: float,
    params: ShadowMassParams,
) -> float:
    rates = rate_vector(d_value, k_value, params)
    return float(np.sum(float(params.lambda_r) * rates * state))


def simulate_shadow_mass(
    m: Any,
    d_stress: Any,
    k_stress: Any,
    params: ShadowMassParams,
    *,
    H: Any | None = None,
    x0: Any | None = None,
    seed: int | None = None,
    clip_state: bool = True,
) -> dict[str, np.ndarray]:
    """Simulate weekly maturity-mass states and observations."""
    params = _positive_params(params)
    m_arr, d_arr, k_arr, _ = _prepare_inputs(m, d_stress, k_stress)
    h = _prepare_h(H)
    rng = np.random.default_rng(seed)
    n = len(m_arr)
    x_prev = np.asarray(x0, dtype=float) if x0 is not None else q_eta(params.eta) * 10.0
    if x_prev.shape != (N_BUCKETS,):
        raise ValueError(f"x0 must have shape ({N_BUCKETS},)")
    x_path = np.zeros((n, N_BUCKETS), dtype=float)
    y_obs = np.zeros((n, h.shape[0]), dtype=float)
    release = np.zeros(n, dtype=float)
    weights = q_eta(params.eta)
    for t in range(n):
        a_t = transition_matrix(d_arr[t], k_arr[t], params)
        b_t = LAMBDA_M * m_arr[t] * weights
        process = rng.normal(0.0, params.sigma_x, size=N_BUCKETS)
        x_t = a_t @ x_prev + b_t + process
        if clip_state:
            x_t = np.clip(x_t, 0.0, None)
        y_obs[t] = h @ x_t + rng.normal(0.0, params.sigma_y, size=h.shape[0])
        x_path[t] = x_t
        release[t] = _release_flow_for_state(x_t, d_arr[t], k_arr[t], params)
        x_prev = x_t
    return {
        "X": x_path,
        "y": y_obs[:, 0] if y_obs.shape[1] == 1 else y_obs,
        "release_flow": release,
        "x_stock_agg": x_path.sum(axis=1),
        "short_share": (x_path[:, 0] + x_path[:, 1]) / np.maximum(x_path.sum(axis=1), 1e-12),
        "m": m_arr,
        "d_stress": d_arr,
        "k_stress": k_arr,
        "H": h,
    }


def kalman_filter_likelihood(
    obs: Any,
    m: Any,
    d_stress: Any,
    k_stress: Any,
    params: ShadowMassParams,
    H: Any | None = None,
    *,
    x0: Any | None = None,
    p0_scale: float = 10.0,
) -> float:
    """Return Gaussian Kalman log likelihood for the conditionally linear model."""
    params = _positive_params(params)
    m_arr, d_arr, k_arr, obs_arr = _prepare_inputs(m, d_stress, k_stress, obs)
    assert obs_arr is not None
    h = _prepare_h(H, obs_arr.shape[1])
    x = np.asarray(x0, dtype=float) if x0 is not None else _default_initial_state(obs_arr, params)
    if x.shape != (N_BUCKETS,):
        raise ValueError(f"x0 must have shape ({N_BUCKETS},)")
    p = np.eye(N_BUCKETS, dtype=float) * float(p0_scale)
    q = np.eye(N_BUCKETS, dtype=float) * params.sigma_x**2
    loglike = 0.0
    weights = q_eta(params.eta)
    for t in range(len(m_arr)):
        a_t = transition_matrix(d_arr[t], k_arr[t], params)
        x_pred = a_t @ x + LAMBDA_M * m_arr[t] * weights
        p_pred = a_t @ p @ a_t.T + q
        y_t = obs_arr[t]
        finite = np.isfinite(y_t)
        if np.any(finite):
            h_t = h[finite]
            innovation = y_t[finite] - h_t @ x_pred
            r_t = np.eye(int(np.sum(finite)), dtype=float) * params.sigma_y**2
            s_t = h_t @ p_pred @ h_t.T + r_t
            sign, logdet = np.linalg.slogdet(s_t)
            if sign <= 0 or not np.isfinite(logdet):
                return -np.inf
            try:
                solved = np.linalg.solve(s_t, innovation)
                gain = np.linalg.solve(s_t, h_t @ p_pred).T
            except np.linalg.LinAlgError:
                return -np.inf
            loglike += -0.5 * (
                len(innovation) * np.log(2.0 * np.pi) + logdet + float(innovation @ solved)
            )
            x = x_pred + gain @ innovation
            p = (np.eye(N_BUCKETS) - gain @ h_t) @ p_pred
            p = 0.5 * (p + p.T)
        else:
            x, p = x_pred, p_pred
    return float(loglike)


def _filter_states(
    obs: Any,
    m: Any,
    d_stress: Any,
    k_stress: Any,
    params: ShadowMassParams,
    H: Any | None = None,
    *,
    x0: Any | None = None,
    p0_scale: float = 10.0,
    clip_state: bool = True,
) -> np.ndarray:
    params = _positive_params(params)
    m_arr, d_arr, k_arr, obs_arr = _prepare_inputs(m, d_stress, k_stress, obs)
    assert obs_arr is not None
    h = _prepare_h(H, obs_arr.shape[1])
    x = np.asarray(x0, dtype=float) if x0 is not None else _default_initial_state(obs_arr, params)
    p = np.eye(N_BUCKETS, dtype=float) * float(p0_scale)
    q = np.eye(N_BUCKETS, dtype=float) * params.sigma_x**2
    weights = q_eta(params.eta)
    states = np.zeros((len(m_arr), N_BUCKETS), dtype=float)
    for t in range(len(m_arr)):
        a_t = transition_matrix(d_arr[t], k_arr[t], params)
        x_pred = a_t @ x + LAMBDA_M * m_arr[t] * weights
        p_pred = a_t @ p @ a_t.T + q
        y_t = obs_arr[t]
        finite = np.isfinite(y_t)
        if np.any(finite):
            h_t = h[finite]
            innovation = y_t[finite] - h_t @ x_pred
            s_t = h_t @ p_pred @ h_t.T + np.eye(int(np.sum(finite))) * params.sigma_y**2
            try:
                gain = np.linalg.solve(s_t, h_t @ p_pred).T
            except np.linalg.LinAlgError:
                gain = np.linalg.pinv(s_t) @ h_t @ p_pred
                gain = gain.T
            x = x_pred + gain @ innovation
            p = (np.eye(N_BUCKETS) - gain @ h_t) @ p_pred
            p = 0.5 * (p + p.T)
        else:
            x, p = x_pred, p_pred
        if clip_state:
            x = np.clip(x, 0.0, None)
        states[t] = x
    return states


def filter_shadow_mass(
    obs: Any,
    m: Any,
    d_stress: Any,
    k_stress: Any,
    params: ShadowMassParams,
    H: Any | None = None,
    *,
    x0: Any | None = None,
) -> pd.DataFrame:
    """Filter latent shadow mass and derived diagnostics."""
    m_arr, d_arr, k_arr, _ = _prepare_inputs(m, d_stress, k_stress, obs)
    states = _filter_states(obs, m_arr, d_arr, k_arr, params, H, x0=x0)
    baseline = replace(_positive_params(params), rho_d=0.0, rho_k=0.0)
    baseline_states = _filter_states(obs, m_arr, d_arr, k_arr, baseline, H, x0=x0)
    x_agg = states.sum(axis=1)
    base_agg = baseline_states.sum(axis=1)
    release = np.array(
        [_release_flow_for_state(states[t], d_arr[t], k_arr[t], _positive_params(params)) for t in range(len(m_arr))]
    )
    out = pd.DataFrame(
        {
            "x_stock_agg": x_agg,
            "release_flow": release,
            "short_share": (states[:, 0] + states[:, 1]) / np.maximum(x_agg, 1e-12),
            "mf_gap": np.abs(x_agg - base_agg),
        }
    )
    for j in range(N_BUCKETS):
        out[f"x_bucket_{j}"] = states[:, j]
    return out


def _initial_params(obs: Any, initial_params: ShadowMassParams | None) -> ShadowMassParams:
    if initial_params is not None:
        return _positive_params(initial_params)
    obs_arr = np.asarray(obs, dtype=float)
    finite = obs_arr[np.isfinite(obs_arr)]
    scale = float(np.nanstd(finite)) if finite.size else 0.05
    sigma_y = max(scale * 0.05, 0.02)
    return ShadowMassParams(
        lambda_r=0.30,
        eta=0.20,
        rho0=0.05,
        rho_d=0.40,
        rho_k=0.35,
        rho_xi=0.0,
        kappa=0.05,
        sigma_x=0.02,
        sigma_y=sigma_y,
    )


def fit_shadow_mass_mle(
    obs: Any,
    m: Any,
    d_stress: Any,
    k_stress: Any,
    *,
    H: Any | None = None,
    initial_params: ShadowMassParams | None = None,
    fixed_params: dict[str, float] | None = None,
    maxiter: int = 100,
) -> ShadowMassParams:
    """Fit non-negative parameters by bounded L-BFGS-B maximum likelihood."""
    from scipy.optimize import minimize

    fixed_params = dict(fixed_params or {})
    unknown = [name for name in _PARAM_NAMES if name not in fixed_params]
    start = _initial_params(obs, initial_params)
    x_start = np.array([getattr(start, name) for name in unknown], dtype=float)
    bounds = []
    for name in unknown:
        if name in {"sigma_x", "sigma_y"}:
            bounds.append((1e-6, None))
        else:
            bounds.append((0.0, None))

    def unpack(values: np.ndarray) -> ShadowMassParams:
        raw = {name: float(value) for name, value in zip(unknown, values, strict=True)}
        raw.update({name: float(value) for name, value in fixed_params.items()})
        for name in _PARAM_NAMES:
            raw.setdefault(name, getattr(start, name))
        return _positive_params(ShadowMassParams(**raw))

    def objective(values: np.ndarray) -> float:
        params = unpack(values)
        ll = kalman_filter_likelihood(obs, m, d_stress, k_stress, params, H=H)
        if not np.isfinite(ll):
            return 1e30
        return -ll

    result = minimize(
        objective,
        x_start,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": int(maxiter), "ftol": 1e-8},
    )
    return unpack(np.asarray(result.x, dtype=float))


def _demo(args: argparse.Namespace) -> dict[str, float]:
    rng = np.random.default_rng(args.seed)
    n = int(args.weeks)
    truth = ShadowMassParams(
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
    m = rng.gamma(shape=2.0, scale=0.08, size=n)
    d = np.clip(0.35 + 0.25 * np.sin(np.arange(n) / 18.0) + rng.normal(0.0, 0.04, n), 0, None)
    k = np.clip(0.30 + 0.20 * np.cos(np.arange(n) / 23.0) + rng.normal(0.0, 0.04, n), 0, None)
    sim = simulate_shadow_mass(m, d, k, truth, seed=args.seed + 1)
    fit = fit_shadow_mass_mle(
        sim["y"],
        m,
        d,
        k,
        fixed_params={
            "eta": truth.eta,
            "rho0": truth.rho0,
            "rho_xi": 0.0,
            "kappa": truth.kappa,
            "sigma_x": truth.sigma_x,
            "sigma_y": truth.sigma_y,
        },
        maxiter=args.maxiter,
    )
    return asdict(fit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-fit the shadow mass model on synthetic data.")
    parser.add_argument("--weeks", type=int, default=500)
    parser.add_argument("--maxiter", type=int, default=80)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    for key, value in _demo(args).items():
        print(f"{key}={value:.6g}")


if __name__ == "__main__":
    main()
