from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RollingDispersion:
    """
    Time series of rolling dispersion statistics for a single proxy series.

    std_series and iqr_series have the same index as the input series.
    stability_score summarises how much dispersion expanded in recent windows.
    """

    window: int
    std_series: pd.Series
    iqr_series: pd.Series
    # Ratio of std in the last `window` observations vs the full series std.
    # > 1.0 means recent volatility is higher than historical — dispersion expanding.
    stability_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "stability_score": self.stability_score,
            "latest_std": float(self.std_series.iloc[-1]) if not self.std_series.empty else None,
            "latest_iqr": float(self.iqr_series.iloc[-1]) if not self.iqr_series.empty else None,
        }


@dataclass(frozen=True)
class CrossWindowStability:
    """
    Compares dispersion between two rolling windows (short vs long).

    std_ratio > 1.0 means short window is more volatile than long window.
    is_expanding: dispersion is widening in the recent window.
    """

    window_a_label: str
    window_b_label: str
    std_ratio: float        # window_b.std / window_a.std (b = shorter/recent)
    iqr_ratio: float
    mean_shift: float       # abs(window_b.mean - window_a.mean)
    is_expanding: bool      # std_ratio > 1.0
    is_bimodal_hint: bool   # crude: iqr > 1.5 * std suggests multi-modal spread

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_a_label": self.window_a_label,
            "window_b_label": self.window_b_label,
            "std_ratio": self.std_ratio,
            "iqr_ratio": self.iqr_ratio,
            "mean_shift": self.mean_shift,
            "is_expanding": self.is_expanding,
            "is_bimodal_hint": self.is_bimodal_hint,
        }


def compute_rolling_dispersion(series: pd.Series, window: int) -> RollingDispersion:
    """Compute rolling std and IQR over a fixed window in calendar observations."""
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)

    std_series = clean.rolling(window=window, min_periods=max(2, window // 2)).std(ddof=1)
    iqr_series = clean.rolling(window=window, min_periods=max(2, window // 2)).apply(
        lambda x: float(np.percentile(x[~np.isnan(x)], 75) - np.percentile(x[~np.isnan(x)], 25))
        if np.sum(~np.isnan(x)) >= 2 else np.nan,
        raw=True,
    )

    full_std = float(clean.std(ddof=1)) if clean.notna().sum() >= 2 else 1.0
    recent_std_vals = std_series.dropna()
    recent_std = float(recent_std_vals.iloc[-1]) if not recent_std_vals.empty else full_std
    stability_score = (recent_std / full_std) if full_std > 0 else 1.0

    return RollingDispersion(
        window=window,
        std_series=std_series,
        iqr_series=iqr_series,
        stability_score=stability_score,
    )


def compute_cross_window_stability(
    series: pd.Series,
    window_a: int,
    window_b: int,
    window_a_label: str | None = None,
    window_b_label: str | None = None,
) -> CrossWindowStability:
    """
    Compare dispersion in the last `window_a` observations (long/baseline)
    versus the last `window_b` observations (short/recent).

    Typical call: window_a=252, window_b=63 compares 1-year vs 3-month.
    """
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()

    def _window_stats(n: int) -> tuple[float, float, float]:
        window_vals = clean.iloc[-n:] if len(clean) >= n else clean
        arr = window_vals.to_numpy(dtype=float)
        if len(arr) < 2:
            return 0.0, 0.0, 0.0
        std = float(np.std(arr, ddof=1))
        iqr = float(np.percentile(arr, 75) - np.percentile(arr, 25))
        mean = float(np.mean(arr))
        return std, iqr, mean

    std_a, iqr_a, mean_a = _window_stats(window_a)
    std_b, iqr_b, mean_b = _window_stats(window_b)

    std_ratio = (std_b / std_a) if std_a > 0 else 1.0
    iqr_ratio = (iqr_b / iqr_a) if iqr_a > 0 else 1.0
    mean_shift = abs(mean_b - mean_a)

    # Bimodal hint: IQR much larger than std suggests spread across two modes
    is_bimodal_hint = bool(std_b > 0 and (iqr_b / std_b) > 1.5)

    return CrossWindowStability(
        window_a_label=window_a_label or f"{window_a}obs",
        window_b_label=window_b_label or f"{window_b}obs",
        std_ratio=std_ratio,
        iqr_ratio=iqr_ratio,
        mean_shift=mean_shift,
        is_expanding=std_ratio > 1.0,
        is_bimodal_hint=is_bimodal_hint,
    )
