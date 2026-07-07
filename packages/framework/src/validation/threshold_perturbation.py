from __future__ import annotations

import pandas as pd


PERTURBATIONS = (-0.30, -0.20, -0.10, -0.05, 0.05, 0.10, 0.20, 0.30)


def run_threshold_perturbation(
    score: pd.Series,
    base_threshold: float,
    perturbations: tuple[float, ...] = PERTURBATIONS,
) -> pd.DataFrame:
    base_signal = score.ge(base_threshold)
    base_rank = score.rank(pct=True)
    rows: list[dict[str, float]] = []
    for pct in perturbations:
        threshold = base_threshold * (1.0 + pct)
        shifted = score.ge(threshold)
        rows.append(
            {
                "threshold_perturbation": pct,
                "threshold": threshold,
                "signal_flip_rate": float(base_signal.ne(shifted).mean()),
                "ranking_stability": float(base_rank.corr(score.rank(pct=True)) or 1.0),
                "metric_degradation": float(max(0.0, base_signal.mean() - shifted.mean())),
            }
        )
    return pd.DataFrame.from_records(rows)
