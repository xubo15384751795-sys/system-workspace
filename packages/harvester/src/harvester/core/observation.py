"""Observation-time coverage helpers for release validation.

The release date in a manifest is metadata about the release.  It is not a
substitute for the observation dates contained in the published bytes.  This
module is the single small reader used by staging and finalization to derive
the actual observation interval.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


class ObservationCoverageError(ValueError):
    """Raised when a data file cannot yield a trustworthy observation range."""


def observation_coverage_from_frame(
    frame: pd.DataFrame,
    *,
    time_column: str,
) -> dict[str, Any] | None:
    """Return the actual inclusive date range for a frame.

    ``None`` is intentional for an empty frame.  Empty datasets must be
    represented by their row count and cannot claim an observation interval.
    """
    if time_column not in frame.columns:
        raise ObservationCoverageError(f"time column missing: {time_column}")
    if frame.empty:
        return None

    parsed = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
    invalid_count = int(parsed.isna().sum())
    if invalid_count:
        raise ObservationCoverageError(
            f"time column {time_column!r} contains {invalid_count} unparseable values"
        )

    return {
        "start": parsed.min().date().isoformat(),
        "end": parsed.max().date().isoformat(),
        "time_column": time_column,
        "row_count": int(len(frame)),
    }


def read_observation_coverage(
    path: Path | str,
    *,
    file_format: str,
    time_column: str,
) -> dict[str, Any] | None:
    """Read only the time column needed to derive published-byte coverage."""
    data_path = Path(path)
    normalized_format = file_format.lower().strip()
    try:
        if normalized_format == "parquet":
            frame = pd.read_parquet(data_path, columns=[time_column])
        elif normalized_format == "csv":
            frame = pd.read_csv(data_path, usecols=[time_column])
        elif normalized_format == "tsv":
            frame = pd.read_csv(data_path, sep="\t", usecols=[time_column])
        elif normalized_format == "jsonl":
            frame = pd.read_json(data_path, lines=True)
        elif normalized_format == "json":
            frame = pd.read_json(data_path)
        elif normalized_format == "feather":
            frame = pd.read_feather(data_path, columns=[time_column])
        else:
            raise ObservationCoverageError(
                f"observation coverage reader unavailable for format: {normalized_format}"
            )
    except ObservationCoverageError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ObservationCoverageError(
            f"unable to read {time_column!r} from {data_path}: {type(exc).__name__}: {exc}"
        ) from exc

    return observation_coverage_from_frame(frame, time_column=time_column)


__all__ = [
    "ObservationCoverageError",
    "observation_coverage_from_frame",
    "read_observation_coverage",
]
