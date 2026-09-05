from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.data.distribution.summary import DistributionSummary


@dataclass(frozen=True)
class WindowTransition:
    """
    Captures how the distribution of a channel shifted between two windows.

    This is the Transition layer — complementing static snapshots with
    window-to-window movement signals.
    """

    channel: str
    from_label: str     # e.g. "252d" (longer / baseline window)
    to_label: str       # e.g. "63d"  (shorter / recent window)
    as_of: str

    # Level shift
    mean_shift: float | None            # to.mean - from.mean
    median_shift: float | None          # to.q50 - from.q50

    # Dispersion change
    variance_ratio: float | None        # to.var / from.var  (> 1 = expanding)
    std_ratio: float | None
    iqr_ratio: float | None

    # Tail changes
    tail_mass_upper_change: float | None    # to.tail_upper - from.tail_upper
    tail_mass_lower_change: float | None

    # Shape changes
    skewness_shift: float | None        # to.skewness - from.skewness
    kurtosis_shift: float | None        # to.kurtosis - from.kurtosis

    # Derived flags
    is_expanding: bool          # variance increasing
    is_shifting_right: bool     # mean moving up
    is_tail_thickening: bool    # upper tail mass growing
    is_regime_shift_hint: bool  # large mean_shift AND variance expanding

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "from_label": self.from_label,
            "to_label": self.to_label,
            "as_of": self.as_of,
            "mean_shift": self.mean_shift,
            "median_shift": self.median_shift,
            "variance_ratio": self.variance_ratio,
            "std_ratio": self.std_ratio,
            "iqr_ratio": self.iqr_ratio,
            "tail_mass_upper_change": self.tail_mass_upper_change,
            "tail_mass_lower_change": self.tail_mass_lower_change,
            "skewness_shift": self.skewness_shift,
            "kurtosis_shift": self.kurtosis_shift,
            "is_expanding": self.is_expanding,
            "is_shifting_right": self.is_shifting_right,
            "is_tail_thickening": self.is_tail_thickening,
            "is_regime_shift_hint": self.is_regime_shift_hint,
        }


def compute_transition(
    from_summary: DistributionSummary,
    to_summary: DistributionSummary,
) -> WindowTransition:
    """
    Compute a WindowTransition from two DistributionSummary objects.

    Typically from_summary is the longer/baseline window and to_summary
    is the shorter/recent window.
    """

    def _diff(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return b - a

    def _ratio(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or a == 0:
            return None
        return b / a

    mean_shift = _diff(from_summary.mean, to_summary.mean)
    median_shift = _diff(from_summary.q50, to_summary.q50)
    variance_ratio = _ratio(from_summary.variance, to_summary.variance)
    std_ratio = _ratio(from_summary.std, to_summary.std)
    iqr_ratio = _ratio(from_summary.iqr, to_summary.iqr)
    tail_upper_change = _diff(from_summary.tail_prob_upper, to_summary.tail_prob_upper)
    tail_lower_change = _diff(from_summary.tail_prob_lower, to_summary.tail_prob_lower)
    skewness_shift = _diff(from_summary.skewness, to_summary.skewness)
    kurtosis_shift = _diff(from_summary.kurtosis, to_summary.kurtosis)

    is_expanding = bool(variance_ratio is not None and variance_ratio > 1.0)
    is_shifting_right = bool(mean_shift is not None and mean_shift > 0)
    is_tail_thickening = bool(tail_upper_change is not None and tail_upper_change > 0.01)

    # Regime shift hint: both a large mean movement and expanding variance
    mean_shift_large = (
        mean_shift is not None
        and from_summary.std is not None
        and from_summary.std > 0
        and abs(mean_shift) > 0.5 * from_summary.std
    )
    is_regime_shift_hint = bool(mean_shift_large and is_expanding)

    return WindowTransition(
        channel=from_summary.channel,
        from_label=from_summary.window_label,
        to_label=to_summary.window_label,
        as_of=to_summary.as_of,
        mean_shift=mean_shift,
        median_shift=median_shift,
        variance_ratio=variance_ratio,
        std_ratio=std_ratio,
        iqr_ratio=iqr_ratio,
        tail_mass_upper_change=tail_upper_change,
        tail_mass_lower_change=tail_lower_change,
        skewness_shift=skewness_shift,
        kurtosis_shift=kurtosis_shift,
        is_expanding=is_expanding,
        is_shifting_right=is_shifting_right,
        is_tail_thickening=is_tail_thickening,
        is_regime_shift_hint=is_regime_shift_hint,
    )


def build_multi_window_transitions(
    series: pd.Series,
    channel: str,
    as_of: str,
    windows: list[tuple[int, str]] | None = None,
) -> list[WindowTransition]:
    """
    Build a cascade of WindowTransitions from a series across multiple windows.

    Default windows: [(252, "1y"), (126, "6m"), (63, "3m"), (21, "1m")]
    Each adjacent pair (longer -> shorter) produces one transition.
    """
    if windows is None:
        windows = [(252, "1y"), (126, "6m"), (63, "3m"), (21, "1m")]

    summaries = []
    for n, label in windows:
        window_series = series.iloc[-n:] if len(series) >= n else series
        summaries.append(
            DistributionSummary.from_series(window_series, channel=channel, window_label=label, as_of=as_of)
        )

    transitions = []
    for i in range(len(summaries) - 1):
        transitions.append(compute_transition(summaries[i], summaries[i + 1]))

    return transitions
