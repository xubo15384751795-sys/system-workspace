from __future__ import annotations

import pandas as pd


CHANNELS = ("M", "D", "K", "X")


def run_proxy_ablation(channels: pd.DataFrame, baseline_score: pd.Series | None = None) -> pd.DataFrame:
    base = baseline_score if baseline_score is not None else _joint(channels)
    rows: list[dict[str, float | str]] = []
    base_rank = base.rank(pct=True)
    for channel in CHANNELS:
        ablated = channels.copy()
        if channel in ablated:
            ablated[channel] = 0.0
        score = _joint(ablated)
        rows.append(
            {
                "test": f"remove_{channel}_basket",
                "signal_flip_rate": _flip_rate(base, score),
                "ranking_stability": float(base_rank.corr(score.rank(pct=True)) or 0.0),
                "metric_degradation": float(max(0.0, base.mean() - score.mean())),
            }
        )
    return pd.DataFrame.from_records(rows)


def _joint(channels: pd.DataFrame) -> pd.Series:
    work = pd.DataFrame(index=channels.index)
    work["M"] = pd.to_numeric(channels.get("M", 0.0), errors="coerce").clip(lower=0.0)
    work["D"] = pd.to_numeric(-channels.get("D", 0.0), errors="coerce").clip(lower=0.0)
    work["K"] = pd.to_numeric(channels.get("K", 0.0), errors="coerce").clip(lower=0.0)
    work["X"] = pd.to_numeric(channels.get("X", 0.0), errors="coerce").clip(lower=0.0)
    return work.fillna(0.0).mean(axis=1)


def _flip_rate(a: pd.Series, b: pd.Series) -> float:
    threshold = a.quantile(0.8)
    return float(a.ge(threshold).ne(b.ge(threshold)).mean())
