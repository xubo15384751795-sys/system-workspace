"""Coupled iterative proxy aggregation for M/D/K/X channels.

Replaces independent np.mean aggregation with a coupled solver based on
ODE drift equations. Each channel's value depends on the others through
coupling coefficients derived from the deformation-framework's state
evolution model.

Algorithm:
    1. Independent init: M_init, D_init, K_init, X_init from proxy baskets
    2. Iterative coupling: M depends on D,X; D depends on M; K depends on M,D;
       X depends on M,D,K
    3. Convergence check: stop when max change < tol
    4. Fallback: if no convergence, use last iteration values

Coupling coefficients (from deformation-framework ODE engine):
    alpha = 0.1   (relaxation rate)
    beta  = 0.05  (cross-channel coupling)
    chi   = 0.05  (M←D coupling, from Ṁ = F_S(z) - χ·M + ω·X)
    omega = 0.05  (M←X coupling)
    gamma = 0.03  (X←M,D,K coupling)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Default coupling coefficients from ODE engine
DEFAULT_ALPHA = 0.1    # relaxation rate
DEFAULT_BETA = 0.05    # cross-channel coupling
DEFAULT_CHI = 0.05     # M←D coupling
DEFAULT_OMEGA = 0.05   # M←X coupling
DEFAULT_GAMMA = 0.03   # X←M,D,K coupling


def coupled_aggregate(
    component_values: pd.DataFrame,
    channel_specs: dict[str, list[str]],
    *,
    max_iter: int = 10,
    tol: float = 1e-3,
    alpha: float = DEFAULT_ALPHA,
    beta: float = DEFAULT_BETA,
    chi: float = DEFAULT_CHI,
    omega: float = DEFAULT_OMEGA,
    gamma: float = DEFAULT_GAMMA,
    clip_bounds: tuple[float, float] = (-4.0, 4.0),
) -> pd.DataFrame:
    """Aggregate proxy components with cross-channel coupling.

    Args:
        component_values: DataFrame with proxy component columns, indexed by date.
        channel_specs: Mapping of channel name → list of component column names.
            Expected keys: "M", "D_contraction" (or "D"), "K", "X_agg" (or "X").
        max_iter: Maximum iterations before fallback.
        tol: Convergence threshold (max absolute change across all channels).
        alpha, beta, chi, omega, gamma: Coupling coefficients.
        clip_bounds: Clip channel values to this range after convergence.

    Returns:
        DataFrame with columns M, D_contraction, K, X_agg (canonical channel names).
    """
    # Normalize channel names
    ch_M = "M"
    ch_D = "D_contraction"
    ch_K = "K"
    ch_X = "X_agg"

    def _independent_mean(names: list[str]) -> pd.Series:
        """Mean of available components (independent proxy basket aggregation)."""
        available = [n for n in names if n in component_values.columns]
        if not available:
            return pd.Series(np.nan, index=component_values.index)
        return component_values[available].mean(axis=1, skipna=True)

    # Step 1: Independent init
    M_prev = _independent_mean(channel_specs.get(ch_M, []))
    D_prev = _independent_mean(channel_specs.get(ch_D, []))
    K_prev = _independent_mean(channel_specs.get(ch_K, []))
    X_prev = _independent_mean(channel_specs.get(ch_X, []))

    # Step 2: Iterative coupling
    for _i in range(max_iter):
        # Coupled update (from ODE drift: Ṁ = F_S(z) - χ·M + ω·X)
        # M_new = independent(obs) - chi * D_prev + omega * X_prev
        M_new = _independent_mean(channel_specs.get(ch_M, [])) - chi * D_prev + omega * X_prev

        # D_new = independent(obs) + alpha * M_new
        D_new = _independent_mean(channel_specs.get(ch_D, [])) + alpha * M_new

        # K_new = independent(obs) + beta * (M_new + D_new)
        K_new = _independent_mean(channel_specs.get(ch_K, [])) + beta * (M_new + D_new)

        # X_new = independent(obs) + gamma * (M_new + D_new + K_new)
        X_new = _independent_mean(channel_specs.get(ch_X, [])) + gamma * (M_new + D_new + K_new)

        # Convergence check
        max_change = pd.concat([
            (M_new - M_prev).abs(),
            (D_new - D_prev).abs(),
            (K_new - K_prev).abs(),
            (X_new - X_prev).abs(),
        ], axis=1).max(axis=1).max()

        if max_change < tol:
            break

        M_prev, D_prev, K_prev, X_prev = M_new, D_new, K_new, X_new

    # Step 3: Clip and return
    result = pd.DataFrame({
        ch_M: M_new.clip(clip_bounds[0], clip_bounds[1]),
        ch_D: D_new.clip(clip_bounds[0], clip_bounds[1]),
        ch_K: K_new.clip(clip_bounds[0], clip_bounds[1]),
        ch_X: X_new.clip(clip_bounds[0], clip_bounds[1]),
    }, index=component_values.index)

    return result
