from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def evaluate_rejection_gates(
    channels: pd.DataFrame | None = None,
    sigma: pd.Series | None = None,
    benchmarks: pd.DataFrame | None = None,
    incremental_metrics: Mapping[str, float] | None = None,
    event_coherence: Mapping[str, bool] | None = None,
    portfolio_metrics: Mapping[str, float] | None = None,
) -> dict[str, bool]:
    incremental_metrics = incremental_metrics or {}
    event_coherence = event_coherence or {}
    portfolio_metrics = portfolio_metrics or {}
    out = {
        "sigma_no_incremental_discrimination": bool(
            incremental_metrics.get("sigma_incremental_auc", 0.0) <= 0.0
            and incremental_metrics.get("sigma_incremental_brier_improvement", 0.0) <= 0.0
        ),
        "k_block_no_increment_after_vol_jump_tail": bool(
            incremental_metrics.get("k_incremental_auc_after_vol_jump_tail", 0.0) <= 0.0
            and incremental_metrics.get("k_incremental_brier_improvement", 0.0) <= 0.0
        ),
        "proxy_blocks_cross_loading_too_high": False,
        "case_sequence_no_coherent_response": bool(event_coherence)
        and not all(bool(v) for v in event_coherence.values()),
        "portfolio_overlay_underperforms_without_tail_benefit": bool(
            portfolio_metrics.get("overlay_excess_return", 0.0) < 0.0
            and portfolio_metrics.get("overlay_drawdown_improvement", 0.0) <= 0.0
            and portfolio_metrics.get("overlay_left_tail_improvement", 0.0) <= 0.0
        ),
    }
    if channels is not None and not channels.empty:
        cols = [col for col in ("M", "D", "K", "X") if col in channels.columns]
        if len(cols) >= 2:
            corr = channels[cols].corr().abs()
            mask = ~np.eye(len(cols), dtype=bool)
            out["proxy_blocks_cross_loading_too_high"] = bool((corr.to_numpy()[mask] > 0.90).any())
    if sigma is not None and benchmarks is not None and "NFCI" in benchmarks.columns:
        aligned = pd.concat(
            [pd.to_numeric(sigma, errors="coerce").rename("sigma"), pd.to_numeric(benchmarks["NFCI"], errors="coerce")],
            axis=1,
        ).dropna()
        if len(aligned) >= 20:
            out["sigma_no_incremental_discrimination"] = out["sigma_no_incremental_discrimination"] or bool(
                aligned["sigma"].corr(aligned["NFCI"]) ** 2 > 0.90
            )
    return out
