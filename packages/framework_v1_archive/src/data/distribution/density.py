from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DensitySummary:
    """
    Histogram-based density summary. Supports shape diagnostics without
    requiring a KDE library — histogram approximation is sufficient for
    tail mass, mode count, and skewness signals.
    """

    n_bins: int
    bin_edges: list[float]
    bin_counts: list[int]   # raw observation counts per bin

    tail_mass_lower: float  # fraction below q10
    tail_mass_upper: float  # fraction above q90
    skewness: float | None
    kurtosis: float | None  # excess kurtosis

    # Crude mode count: number of local maxima in the histogram.
    # 1 = unimodal, 2+ = potentially bimodal / regime-mixture.
    mode_count: int

    is_right_skewed: bool   # skewness > 0.5
    is_fat_tailed: bool     # excess kurtosis > 1.0
    is_multimodal: bool     # mode_count >= 2

    sample_count: int

    def bin_probs(self) -> list[float]:
        total = sum(self.bin_counts)
        if total == 0:
            return [0.0] * self.n_bins
        return [c / total for c in self.bin_counts]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_bins": self.n_bins,
            "bin_edges": self.bin_edges,
            "bin_counts": self.bin_counts,
            "bin_probs": self.bin_probs(),
            "tail_mass_lower": self.tail_mass_lower,
            "tail_mass_upper": self.tail_mass_upper,
            "skewness": self.skewness,
            "kurtosis": self.kurtosis,
            "mode_count": self.mode_count,
            "is_right_skewed": self.is_right_skewed,
            "is_fat_tailed": self.is_fat_tailed,
            "is_multimodal": self.is_multimodal,
            "sample_count": self.sample_count,
        }


def _count_local_maxima(counts: list[int]) -> int:
    """Count local maxima in a histogram bin count array."""
    if len(counts) < 3:
        return 1
    n_maxima = 0
    for i in range(1, len(counts) - 1):
        if counts[i] > counts[i - 1] and counts[i] > counts[i + 1]:
            n_maxima += 1
    if n_maxima == 0:
        # flat or monotone — treat as 1 mode
        return 1
    return n_maxima


def compute_density(series: pd.Series, n_bins: int = 20) -> DensitySummary:
    """Compute histogram-based density summary from a pandas Series."""
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()

    if clean.empty:
        return DensitySummary(
            n_bins=n_bins,
            bin_edges=[],
            bin_counts=[],
            tail_mass_lower=0.0,
            tail_mass_upper=0.0,
            skewness=None,
            kurtosis=None,
            mode_count=0,
            is_right_skewed=False,
            is_fat_tailed=False,
            is_multimodal=False,
            sample_count=0,
        )

    vals = clean.to_numpy(dtype=float)
    n = len(vals)

    counts, edges = np.histogram(vals, bins=n_bins)
    bin_counts = [int(c) for c in counts]
    bin_edges = [float(e) for e in edges]

    q10, q90 = float(np.percentile(vals, 10)), float(np.percentile(vals, 90))
    tail_mass_lower = float(np.mean(vals < q10))
    tail_mass_upper = float(np.mean(vals > q90))

    mean = float(np.mean(vals))
    skewness: float | None = None
    kurtosis: float | None = None
    if n >= 3:
        std = float(np.std(vals, ddof=1))
        if std > 0:
            centered = vals - mean
            skewness = float(np.mean(centered ** 3) / (std ** 3))
            kurtosis = float(np.mean(centered ** 4) / (std ** 4)) - 3.0

    mode_count = _count_local_maxima(bin_counts)

    is_right_skewed = bool(skewness is not None and skewness > 0.5)
    is_fat_tailed = bool(kurtosis is not None and kurtosis > 1.0)
    is_multimodal = mode_count >= 2

    return DensitySummary(
        n_bins=n_bins,
        bin_edges=bin_edges,
        bin_counts=bin_counts,
        tail_mass_lower=tail_mass_lower,
        tail_mass_upper=tail_mass_upper,
        skewness=skewness,
        kurtosis=kurtosis,
        mode_count=mode_count,
        is_right_skewed=is_right_skewed,
        is_fat_tailed=is_fat_tailed,
        is_multimodal=is_multimodal,
        sample_count=n,
    )
