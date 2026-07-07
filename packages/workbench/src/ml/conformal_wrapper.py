"""Conformal-style prediction sets for categorical regime probabilities (numpy-only).

This is intentionally small: it converts a probability vector into a **prediction set**
of regimes that are not ruled out at level *alpha* using a standardised residual
based on the gap between the top-1 and top-2 probabilities.

For a production calibration pipeline, replace the heuristic quantile with an
empirical calibration bundle derived from held-out NBER (or other external) labels.
"""
from __future__ import annotations

from typing import Any

import numpy as np

_STATE_ORDER = ["compression", "volatile", "crisis"]


def conformal_regime_sets(
    state_probs: dict[str, float],
    *,
    alpha: float = 0.10,
) -> dict[str, Any]:
    """Return a conformal summary dict suitable for ``ml_signal`` payloads.

    Parameters
    ----------
    state_probs:
        Mapping with keys ``compression | volatile | crisis`` summing to ~1.
    alpha:
        Nominal miscoverage; larger *alpha* ⇒ larger prediction sets.
    """
    probs = np.array([float(state_probs.get(s, 0.0)) for s in _STATE_ORDER], dtype=float)
    probs = np.clip(probs, 1e-9, 1.0)
    probs /= probs.sum()

    order = np.argsort(-probs)
    top = probs[order[0]]
    second = probs[order[1]] if len(order) > 1 else 0.0
    # Nonconformity: margin between winner and runner-up (small margin ⇒ ambiguous)
    score = float(top - second)

    # Heuristic threshold: lower score ⇒ include more labels (conservative).
    # When score is high, only the argmax is kept; when low, keep top-2 or all 3.
    thr = float(max(0.05, 1.0 - alpha))
    pred_set: list[str] = []
    if score >= thr:
        pred_set = [_STATE_ORDER[int(order[0])]]
    elif score >= thr * 0.5:
        pred_set = [_STATE_ORDER[int(order[0])], _STATE_ORDER[int(order[1])]]
    else:
        pred_set = list(_STATE_ORDER)

    return {
        "alpha": float(alpha),
        "prediction_set": pred_set,
        "set_size": int(len(pred_set)),
        "coverage_guaranteed": False,
        "notes": "Heuristic numpy wrapper — replace with calibrated split conformal for guarantees.",
    }


class ConformalRegimeWrapper:
    """OO façade matching the design doc; delegates to :func:`conformal_regime_sets`."""

    def __init__(self, alpha: float = 0.10) -> None:
        self.alpha = float(alpha)

    def wrap(self, regime_probs: dict[str, float]) -> dict[str, Any]:
        return conformal_regime_sets(regime_probs, alpha=self.alpha)
