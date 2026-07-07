from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EvaluationMetrics:
    auc: float
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    calm_period_false_alarm_rate: float
    average_lead_time: float | None
    warning_duration: float
    baseline_rank: int | None
    crisis_recall: float
    non_crisis_behavior: str


def evaluate_binary_signal(
    signal: pd.Series,
    target: pd.Series,
    threshold: float,
    crisis_mask: pd.Series | None = None,
    baseline_scores: dict[str, float] | None = None,
) -> EvaluationMetrics:
    aligned = pd.concat([signal.rename("signal"), target.rename("target")], axis=1).dropna()
    if aligned.empty:
        return EvaluationMetrics(0.5, 0.0, 0.0, 0.0, 0.0, 0.0, None, 0.0, None, 0.0, "insufficient_data")
    y = aligned["target"].astype(bool)
    scores = pd.to_numeric(aligned["signal"], errors="coerce").fillna(0.0)
    pred = scores.ge(threshold)
    tp = int((pred & y).sum())
    fp = int((pred & ~y).sum())
    fn = int((~pred & y).sum())
    tn = int((~pred & ~y).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    calm_alarm = float(pred[~y].mean()) if (~y).any() else 0.0
    duration = _average_warning_duration(pred)
    auc = _auc(scores, y)
    lead = _average_lead_time(pred, y)
    crisis_recall = recall
    if crisis_mask is not None:
        crisis = crisis_mask.reindex(aligned.index).fillna(False).astype(bool)
        crisis_recall = float((pred[crisis] & y[crisis]).sum() / y[crisis].sum()) if y[crisis].sum() else 0.0
    rank = _baseline_rank(float(f1), baseline_scores)
    behavior = "quiet" if calm_alarm < 0.05 else "noisy" if calm_alarm > 0.2 else "mixed"
    return EvaluationMetrics(auc, precision, recall, f1, fpr, calm_alarm, lead, duration, rank, crisis_recall, behavior)


def metrics_to_dict(metrics: EvaluationMetrics) -> dict[str, float | int | str | None]:
    return metrics.__dict__.copy()


def _auc(scores: pd.Series, target: pd.Series) -> float:
    pos = scores[target]
    neg = scores[~target]
    if pos.empty or neg.empty:
        return 0.5
    comparisons = [(p > n) + 0.5 * (p == n) for p in pos for n in neg]
    return float(np.mean(comparisons)) if comparisons else 0.5


def _average_warning_duration(pred: pd.Series) -> float:
    if pred.empty or not pred.any():
        return 0.0
    groups = (pred != pred.shift(fill_value=False)).cumsum()
    lengths = [len(block) for _, block in pred.groupby(groups) if bool(block.iloc[0])]
    return float(np.mean(lengths)) if lengths else 0.0


def _average_lead_time(pred: pd.Series, target: pd.Series) -> float | None:
    event_dates = target[target].index
    leads: list[int] = []
    for event_date in event_dates:
        prior = pred.loc[:event_date]
        if prior.empty or not prior.any():
            continue
        leads.append(len(prior) - 1 - int(np.flatnonzero(prior.to_numpy())[-1]))
    return float(np.mean(leads)) if leads else None


def _baseline_rank(score: float, baseline_scores: dict[str, float] | None) -> int | None:
    if not baseline_scores:
        return None
    ordered = sorted([score, *baseline_scores.values()], reverse=True)
    return int(ordered.index(score) + 1)
