from __future__ import annotations


from typing import cast

import numpy as np
import pandas as pd

from src.data.cross_section.slice import CrossSectionSlice, _gini, build_cross_section_slice


class CrossSectionAggregator:
    """
    Produces time-series of cross-sectional statistics from an entity panel.

    Input: a DataFrame where:
      - index: DatetimeIndex
      - columns: entity identifiers (issuers, institutions, tenors, etc.)
      - values: the metric of interest (e.g. funding gap, leverage ratio)

    Output:
      - Rolling cross-sectional dispersion (std, iqr, gini across entities)
      - Concentration series (Gini coefficient per timestamp)
      - Point-in-time CrossSectionSlice at any timestamp
    """

    def __init__(
        self,
        dimension: str,
        channel: str,
        measurement_block: str,
    ) -> None:
        self.dimension = dimension
        self.channel = channel
        self.measurement_block = measurement_block

    def slice_at(
        self,
        frame: pd.DataFrame,
        timestamp: str,
        top_tail_n: int = 5,
    ) -> CrossSectionSlice:
        return build_cross_section_slice(
            frame=frame,
            timestamp=timestamp,
            dimension=self.dimension,
            channel=self.channel,
            measurement_block=self.measurement_block,
            top_tail_n=top_tail_n,
        )

    def rolling_dispersion(
        self,
        frame: pd.DataFrame,
        window: int = 20,
    ) -> pd.DataFrame:
        """
        Return a DataFrame indexed like `frame` with columns:
          cross_std, cross_iqr, cross_gini, cross_mean, cross_n

        Each row is the cross-sectional dispersion statistics across all
        entity columns at that timestamp, smoothed via a rolling window.
        """
        clean = frame.apply(pd.to_numeric, errors="coerce")

        def _row_stats(row: pd.Series) -> pd.Series:
            vals = row.dropna().to_numpy(dtype=float)
            if len(vals) < 2:
                return pd.Series({"cross_std": np.nan, "cross_iqr": np.nan,
                                   "cross_gini": np.nan, "cross_mean": np.nan,
                                   "cross_n": float(len(vals))})
            return pd.Series({
                "cross_std": float(np.std(vals, ddof=1)),
                "cross_iqr": float(np.percentile(vals, 75) - np.percentile(vals, 25)),
                "cross_gini": _gini(vals),
                "cross_mean": float(np.mean(vals)),
                "cross_n": float(len(vals)),
            })

        stats = clean.apply(_row_stats, axis=1)

        # Smooth with rolling window to reduce noise
        smoothed = stats.rolling(window=window, min_periods=1).mean()
        smoothed["cross_n"] = stats["cross_n"]  # keep raw entity count

        return smoothed

    def concentration_series(self, frame: pd.DataFrame) -> pd.Series:
        """
        Return a Series of Gini coefficients indexed like `frame`.

        High Gini => risk concentrated in few entities.
        Low Gini  => spread evenly across entities.
        """
        clean = frame.apply(pd.to_numeric, errors="coerce")

        def _gini_row(row: pd.Series) -> float:
            vals = row.dropna().to_numpy(dtype=float)
            if len(vals) < 2:
                return np.nan
            return cast(float, _gini(vals))

        return clean.apply(_gini_row, axis=1).rename("gini_concentration")

    def tail_entity_frequency(
        self,
        frame: pd.DataFrame,
        quantile: float = 0.9,
    ) -> pd.Series:
        """
        For each entity (column), return the fraction of timestamps where
        it was in the top-quantile tail of the cross section.

        Identifies structurally persistent tail entities — those that
        consistently accumulate risk rather than appearing in the tail randomly.
        """
        clean = frame.apply(pd.to_numeric, errors="coerce")
        thresholds = clean.quantile(quantile, axis=1)

        tail_flags = clean.gt(thresholds, axis=0)
        return tail_flags.mean(axis=0).rename("tail_frequency")
