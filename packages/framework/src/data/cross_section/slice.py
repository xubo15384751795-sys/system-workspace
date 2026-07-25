from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CrossSectionSlice:
    """
    Point-in-time snapshot of a metric across a set of entities.

    'Entities' can be: issuers, instruments, tenors, strike levels, institutions.
    This is the cross-sectional complement to a time series level reading.

    Provides the dispersion view that time series alone cannot give:
    - Is the distribution of values across entities wide or narrow?
    - Are a few tail entities driving the aggregate?
    - Is the cross-section concentrating (risk moving to fewer names)?
    """

    timestamp: str              # ISO date
    dimension: str              # "issuer" | "tenor" | "strike" | "institution" | ...
    channel: str                # M / D / K / X
    measurement_block: str

    values: dict[str, float]    # entity_id -> value

    # Distributional stats across entities
    mean: float | None
    std: float | None
    iqr: float | None
    q10: float | None
    q50: float | None
    q90: float | None

    # Concentration
    gini: float | None          # 0 = equal spread, 1 = fully concentrated
    n_entities: int

    # Tail entities (above q90)
    top_tail_entities: list[str] = field(default_factory=list)
    # Bottom tail entities (below q10)
    bottom_tail_entities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "dimension": self.dimension,
            "channel": self.channel,
            "measurement_block": self.measurement_block,
            "n_entities": self.n_entities,
            "mean": self.mean,
            "std": self.std,
            "iqr": self.iqr,
            "q10": self.q10,
            "q50": self.q50,
            "q90": self.q90,
            "gini": self.gini,
            "top_tail_entities": self.top_tail_entities,
            "bottom_tail_entities": self.bottom_tail_entities,
        }


def _gini(vals: np.ndarray) -> float:
    """Gini coefficient for a 1-D array of non-negative values."""
    arr = np.abs(vals)
    if arr.sum() == 0:
        return 0.0
    arr = np.sort(arr)
    n = len(arr)
    cumsum = np.cumsum(arr)
    return float((n + 1 - 2 * np.sum(cumsum) / cumsum[-1]) / n)


def build_cross_section_slice(
    frame: pd.DataFrame,
    timestamp: str,
    dimension: str,
    channel: str,
    measurement_block: str,
    top_tail_n: int = 5,
) -> CrossSectionSlice:
    """
    Build a CrossSectionSlice from a DataFrame.

    frame layout:
      - rows indexed by date (or a single-row frame)
      - columns are entity identifiers

    If frame has a DatetimeIndex, the row closest to `timestamp` is used.
    If frame has a single row, that row is used directly.
    """
    if isinstance(frame.index, pd.DatetimeIndex) and len(frame) > 1:
        ts = pd.to_datetime(timestamp)
        row = frame.iloc[frame.index.get_indexer([ts], method="nearest")[0]]
    else:
        row = frame.iloc[0] if len(frame) > 0 else pd.Series(dtype=float)

    values: dict[str, float] = {}
    for col in frame.columns:
        v = pd.to_numeric(row.get(col), errors="coerce")
        if pd.notna(v):
            values[str(col)] = float(v)

    if not values:
        return CrossSectionSlice(
            timestamp=timestamp,
            dimension=dimension,
            channel=channel,
            measurement_block=measurement_block,
            values={},
            mean=None, std=None, iqr=None,
            q10=None, q50=None, q90=None,
            gini=None,
            n_entities=0,
        )

    arr = np.array(list(values.values()), dtype=float)
    n = len(arr)

    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if n > 1 else None
    q10, q50, q90 = (float(v) for v in np.percentile(arr, [10, 50, 90]))
    iqr = float(np.percentile(arr, 75) - np.percentile(arr, 25))
    gini = _gini(arr) if n > 1 else None

    sorted_entities = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    top_tail = [eid for eid, v in sorted_entities if v >= q90][:top_tail_n]
    bottom_tail = [eid for eid, v in sorted_entities[::-1] if v <= q10][:top_tail_n]

    return CrossSectionSlice(
        timestamp=timestamp,
        dimension=dimension,
        channel=channel,
        measurement_block=measurement_block,
        values=values,
        mean=mean,
        std=std,
        iqr=iqr,
        q10=q10,
        q50=q50,
        q90=q90,
        gini=gini,
        n_entities=n,
        top_tail_entities=top_tail,
        bottom_tail_entities=bottom_tail,
    )
