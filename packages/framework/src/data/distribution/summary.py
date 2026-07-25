from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DistributionSummary:
    """
    Full distributional characterization of a single channel over a window.

    Covers all three measurement layers:
      - Level:     mean, q50
      - Dispersion: variance, std, iqr, q10, q90
      - Density:   skewness, kurtosis, tail_prob_upper, tail_prob_lower, entropy
    """

    channel: str        # M / D / K / X
    window_label: str   # e.g. "90d", "1y"
    as_of: str          # ISO date string

    # --- level ---
    mean: float | None
    q50: float | None

    # --- dispersion ---
    variance: float | None
    std: float | None
    iqr: float | None
    q10: float | None
    q90: float | None

    # --- density / shape ---
    skewness: float | None
    kurtosis: float | None
    tail_prob_upper: float | None   # fraction of observations above q90
    tail_prob_lower: float | None   # fraction of observations below q10
    entropy: float | None           # Shannon entropy over histogram bins (optional)

    sample_count: int

    # --- derived flags ---
    is_right_skewed: bool = False   # skewness > 0.5
    is_fat_tailed: bool = False     # excess kurtosis > 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "window_label": self.window_label,
            "as_of": self.as_of,
            "mean": self.mean,
            "q50": self.q50,
            "variance": self.variance,
            "std": self.std,
            "iqr": self.iqr,
            "q10": self.q10,
            "q90": self.q90,
            "skewness": self.skewness,
            "kurtosis": self.kurtosis,
            "tail_prob_upper": self.tail_prob_upper,
            "tail_prob_lower": self.tail_prob_lower,
            "entropy": self.entropy,
            "sample_count": self.sample_count,
            "is_right_skewed": self.is_right_skewed,
            "is_fat_tailed": self.is_fat_tailed,
        }

    @classmethod
    def from_series(
        cls,
        series: pd.Series,
        channel: str,
        window_label: str,
        as_of: str,
        entropy_bins: int = 20,
    ) -> DistributionSummary:
        """Compute full distributional summary from a pandas Series."""
        clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()

        if clean.empty:
            return cls(
                channel=channel,
                window_label=window_label,
                as_of=as_of,
                mean=None, q50=None,
                variance=None, std=None, iqr=None, q10=None, q90=None,
                skewness=None, kurtosis=None,
                tail_prob_upper=None, tail_prob_lower=None,
                entropy=None,
                sample_count=0,
            )

        vals = clean.to_numpy(dtype=float)
        n = len(vals)

        mean = float(np.mean(vals))
        variance = float(np.var(vals, ddof=1)) if n > 1 else None
        std = float(np.std(vals, ddof=1)) if n > 1 else None
        q10, q50, q90 = (float(v) for v in np.percentile(vals, [10, 50, 90]))
        iqr = float(np.percentile(vals, 75) - np.percentile(vals, 25))

        # skewness and kurtosis (excess)
        skewness: float | None = None
        kurtosis: float | None = None
        if n >= 3 and std and std > 0:
            centered = vals - mean
            skewness = float(np.mean(centered ** 3) / (std ** 3))
            kurtosis = float(np.mean(centered ** 4) / (std ** 4)) - 3.0  # excess

        tail_prob_upper = float(np.mean(vals > q90)) if n > 0 else None
        tail_prob_lower = float(np.mean(vals < q10)) if n > 0 else None

        # Shannon entropy over histogram
        entropy: float | None = None
        if n >= entropy_bins:
            counts, _ = np.histogram(vals, bins=entropy_bins)
            probs = counts / counts.sum()
            probs = probs[probs > 0]
            entropy = float(-np.sum(probs * np.log(probs)))

        is_right_skewed = bool(skewness is not None and skewness > 0.5)
        is_fat_tailed = bool(kurtosis is not None and kurtosis > 1.0)

        return cls(
            channel=channel,
            window_label=window_label,
            as_of=as_of,
            mean=mean,
            q50=q50,
            variance=variance,
            std=std,
            iqr=iqr,
            q10=q10,
            q90=q90,
            skewness=skewness,
            kurtosis=kurtosis,
            tail_prob_upper=tail_prob_upper,
            tail_prob_lower=tail_prob_lower,
            entropy=entropy,
            sample_count=n,
            is_right_skewed=is_right_skewed,
            is_fat_tailed=is_fat_tailed,
        )


@dataclass
class ChannelDistributionState:
    """
    Holds the current distribution summary for all four channels at a given date.
    This is the distributional analogue to the scalar ProxyReading bundle.
    """

    as_of: str
    M: DistributionSummary | None = None
    D: DistributionSummary | None = None
    K: DistributionSummary | None = None
    X: DistributionSummary | None = None

    def channel(self, name: str) -> DistributionSummary | None:
        return getattr(self, name.upper(), None)

    def available_channels(self) -> list[str]:
        return [ch for ch in ("M", "D", "K", "X") if self.channel(ch) is not None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "M": self.M.to_dict() if self.M else None,
            "D": self.D.to_dict() if self.D else None,
            "K": self.K.to_dict() if self.K else None,
            "X": self.X.to_dict() if self.X else None,
        }

    @classmethod
    def build(
        cls,
        frame: pd.DataFrame,
        window_label: str,
        as_of: str,
        channel_columns: dict[str, str] | None = None,
    ) -> ChannelDistributionState:
        """
        Build from a DataFrame where columns correspond to channel proxy series.

        channel_columns maps channel name -> column name in frame.
        Defaults to {"M": "M_PROXY", "D": "D_PROXY", "K": "K_PROXY", "X": "X_PROXY"}.
        """
        mapping = channel_columns or {
            "M": "M_PROXY",
            "D": "D_PROXY",
            "K": "K_PROXY",
            "X": "X_PROXY",
        }
        summaries: dict[str, DistributionSummary | None] = {}
        for ch, col in mapping.items():
            if col in frame.columns:
                summaries[ch] = DistributionSummary.from_series(
                    frame[col], channel=ch, window_label=window_label, as_of=as_of
                )
            else:
                summaries[ch] = None

        return cls(
            as_of=as_of,
            M=summaries.get("M"),
            D=summaries.get("D"),
            K=summaries.get("K"),
            X=summaries.get("X"),
        )
