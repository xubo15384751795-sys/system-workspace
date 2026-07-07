"""OBS-3: diagnostic static-source risk flags for high-stress event windows (read-only inputs)."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from src.dynamic.integrity_series_metrics import (
    compute_event_window_variance,
    compute_missingness_ratio,
    compute_staleness_score,
    select_event_window,
)
from src.dynamic.observation_integrity import ProviderIntegrityCheck

# Near-zero variance: population variance at or below this is treated as flat for stress checks.
_NEAR_ZERO_VARIANCE = 1e-10
# Consecutive repeat rate at or above this counts as "repeated values dominate".
_REPEAT_DOMINANCE = 0.75
# Missingness buckets (material / severe).
_MISSING_WARN = 0.35
_MISSING_FAIL = 0.75
# Fail when static-source pattern pairs with elevated missingness.
_STATIC_SEVERE_MISSINGNESS = 0.55

_RESOLUTION_RANK: dict[str, int] = {
    "intraday": 0,
    "hourly": 0,
    "h": 0,
    "daily": 1,
    "d": 1,
    "day": 1,
    "business_daily": 1,
    "bd": 1,
    "weekly": 2,
    "w": 2,
    "week": 2,
    "monthly": 3,
    "m": 3,
    "month": 3,
    "quarterly": 4,
    "q": 4,
    "annual": 5,
    "yearly": 5,
    "y": 5,
    "a": 5,
}


def _normalize_resolution_token(s: str) -> str:
    t = s.strip().lower()
    t = re.sub(r"\s+", "_", t)
    return t


def _resolution_rank(label: str | None) -> int | None:
    """Lower rank = finer (more frequent). Unknown tokens → None (no mismatch verdict)."""
    if label is None:
        return None
    key = _normalize_resolution_token(label)
    if key in _RESOLUTION_RANK:
        return _RESOLUTION_RANK[key]
    for token in key.replace("-", "_").split("_"):
        if token in _RESOLUTION_RANK:
            return _RESOLUTION_RANK[token]
    return None


def _resolution_below_requirement(frequency: str | None, required: str | None) -> bool:
    """True if provider cadence is strictly coarser than required (e.g. weekly vs daily)."""
    rf = _resolution_rank(frequency)
    rr = _resolution_rank(required)
    if rf is None or rr is None:
        return False
    return rf > rr


def _consecutive_repeat_rate(values: pd.Series) -> float | None:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if len(v) < 2:
        return None
    vf = v.astype(float)
    return float((vf.iloc[1:].to_numpy() == vf.iloc[:-1].to_numpy()).mean())


def detect_static_source_risk(
    series: pd.Series,
    event_window: tuple[Any, Any] | None,
    high_stress: bool,
    logical_series: str,
    provider: str | None,
    frequency: str | None,
    required_resolution: str | None,
    fallback_used: bool = False,
    mock_used: bool = False,
) -> ProviderIntegrityCheck:
    """Diagnose static-source and observation-quality risk for an event window.

    Does not mutate ``series``. Returns a :class:`ProviderIntegrityCheck` with
    diagnostic fields and machine-friendly ``issues`` codes.

    Detection (issues):
    - ``static_source_risk``: ``high_stress`` and event-window variance is near-zero.
    - ``repeated_values_in_event_window``: consecutive repeat rate ≥ threshold.
    - ``high_missingness``: missingness ≥ material threshold.
    - ``resolution_below_event_requirement``: provider cadence coarser than required (token map).
    - ``fallback_used``: ``fallback_used`` is True.

    Status (highest applicable): ``fail`` > ``warn`` > ``watch`` > ``pass``; ``unknown`` when
    there are fewer than two finite observations and missingness is below the severe threshold.
    ``mock_used`` always yields ``fail``.
    """
    start, end = (None, None)
    if event_window is not None:
        start, end = event_window

    window = select_event_window(series, start, end)
    finite = pd.to_numeric(window, errors="coerce").dropna()
    missingness = compute_missingness_ratio(window)

    issues: list[str] = []
    if fallback_used:
        issues.append("fallback_used")
    if _resolution_below_requirement(frequency, required_resolution):
        issues.append("resolution_below_event_requirement")
    if missingness >= _MISSING_WARN:
        issues.append("high_missingness")

    var: float | None = None
    repeat_rate: float | None = None
    if len(finite) >= 2:
        var = compute_event_window_variance(series, start, end)
        repeat_rate = _consecutive_repeat_rate(window)
        if high_stress and var is not None and var <= _NEAR_ZERO_VARIANCE:
            issues.append("static_source_risk")
        if repeat_rate is not None and repeat_rate >= _REPEAT_DOMINANCE:
            issues.append("repeated_values_in_event_window")

    staleness: float | None
    if len(window) == 0:
        staleness = None
    else:
        staleness = compute_staleness_score(series, start, end)

    has_static_issue = "static_source_risk" in issues
    has_resolution_issue = "resolution_below_event_requirement" in issues
    has_high_missing_issue = "high_missingness" in issues
    has_repeat_issue = "repeated_values_in_event_window" in issues

    insufficient = len(finite) < 2

    if mock_used:
        status: str = "fail"
    elif missingness >= _MISSING_FAIL:
        status = "fail"
    elif insufficient:
        status = "unknown"
    elif has_static_issue and missingness >= _STATIC_SEVERE_MISSINGNESS:
        status = "fail"
    elif has_static_issue or has_resolution_issue or has_high_missing_issue:
        status = "warn"
    elif fallback_used or has_repeat_issue:
        status = "watch"
    else:
        status = "pass"

    interpretation = (
        f"status={status}; missingness={missingness:.3f}; var={var}; "
        f"repeat_rate={repeat_rate}; staleness={staleness}; issues={issues}"
    )

    return ProviderIntegrityCheck(
        logical_series=logical_series,
        provider=provider,
        status=status,
        frequency=frequency,
        required_resolution=required_resolution,
        missingness_ratio=missingness,
        forward_fill_ratio=None,
        event_window_variance=var,
        staleness_score=staleness,
        provider_disagreement=None,
        fallback_used=fallback_used,
        mock_used=mock_used,
        issues=issues,
        interpretation=interpretation,
    )
