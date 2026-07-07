"""Series-level integrity metrics for diagnostics (read-only; no provider mutation)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd


def select_event_window(
    series: pd.Series,
    start: Any = None,
    end: Any = None,
) -> pd.Series:
    """Return the event-window slice (read-only on ``series``); same rules as variance/staleness."""
    return _event_window_slice(series, start, end)


def _event_window_slice(series: pd.Series, start: Any, end: Any) -> pd.Series:
    """Select [start, end] on the time axis when the index is datetime-like; else full series."""
    if start is None and end is None:
        return series
    idx = series.index
    if isinstance(idx, pd.DatetimeIndex):
        left = pd.Timestamp(start) if start is not None else idx.min()
        right = pd.Timestamp(end) if end is not None else idx.max()
        return series.loc[left:right]
    if pd.api.types.is_datetime64_any_dtype(idx):
        left = pd.Timestamp(start) if start is not None else pd.Timestamp(idx.min())
        right = pd.Timestamp(end) if end is not None else pd.Timestamp(idx.max())
        return series.loc[left:right]
    return series


def compute_missingness_ratio(series: pd.Series) -> float:
    """Fraction of observations that are NA (0 = fully observed, 1 = all NA). Empty → 1.0."""
    if len(series) == 0:
        return 1.0
    return float(series.isna().sum()) / float(len(series))


def compute_event_window_variance(
    series: pd.Series,
    start: Any = None,
    end: Any = None,
) -> float | None:
    """Population variance of numeric values in the window; None if fewer than two finite values."""
    window = _event_window_slice(series, start, end)
    values = pd.to_numeric(window, errors="coerce").dropna()
    if len(values) < 2:
        return None
    return float(values.var(ddof=0))


def compute_forward_fill_ratio(
    series: pd.Series,
    metadata: Mapping[str, Any] | None = None,
) -> float | None:
    """Forward-fill fraction from explicit metadata only; otherwise None.

    Recognized metadata keys (first present wins):
    - ``forward_fill_ratio`` or ``forward_fill_fraction``: float in [0, 1]
    - ``forward_fill_count`` with ``series_length`` or ``n``: count / length

    No heuristic is applied to ``series`` when metadata is absent — avoids aggressive inference.
    """
    # Do not inspect ``series`` for forward-fill without explicit metadata.
    _ = series
    if metadata is None:
        return None
    if "forward_fill_ratio" in metadata:
        return float(metadata["forward_fill_ratio"])
    if "forward_fill_fraction" in metadata:
        return float(metadata["forward_fill_fraction"])
    if "forward_fill_count" in metadata:
        count = float(metadata["forward_fill_count"])
        length_key = "series_length" if "series_length" in metadata else "n"
        if length_key not in metadata:
            return None
        length = float(metadata[length_key])
        if length <= 0:
            return None
        return count / length
    return None


def compute_staleness_score(
    series: pd.Series,
    start: Any = None,
    end: Any = None,
) -> float:
    """Diagnostic staleness in [0, 1]: higher for missing, flat, or repeated event-window data.

    Components (weighted average, all in [0, 1]):
    - missingness ratio in the window
    - flatness: ``1 / (1 + population variance)`` on finite values (high variance → lower score)
    - consecutive repeat rate among finite values

    Empty or single-point windows after dropping NA yield a high score (limited information).
    """
    window = _event_window_slice(series, start, end)
    m = compute_missingness_ratio(window)
    values = pd.to_numeric(window, errors="coerce").dropna()
    if len(values) == 0:
        return 1.0
    if len(values) == 1:
        flatness = 1.0
        repeat_rate = 0.0
    else:
        var = float(values.var(ddof=0))
        flatness = 1.0 / (1.0 + var)
        v = values.astype(float)
        repeat_rate = float((v.iloc[1:].to_numpy() == v.iloc[:-1].to_numpy()).mean())
    score = 0.4 * m + 0.35 * flatness + 0.25 * repeat_rate
    return float(min(1.0, max(0.0, score)))
