from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, cast


class QualityCheckError(ValueError):
    """Raised when a generic Harvester quality check fails."""


def check_no_future_dates(df: Any, date_col: str, as_of: date | str) -> None:
    threshold = _as_date(as_of)
    for value in _column_values(df, date_col):
        if value is not None and _as_date(value) > threshold:
            raise QualityCheckError(f"{date_col} contains date after as_of={threshold}: {value}")


def check_monotonic_time(df: Any, time_col: str) -> None:
    previous: Any = None
    for value in _column_values(df, time_col):
        if previous is not None and value < previous:
            raise QualityCheckError(f"{time_col} is not monotonic")
        previous = value


def check_no_nulls_in_required(df: Any, required_cols: Iterable[str]) -> None:
    for column in required_cols:
        for value in _column_values(df, column):
            if value is None or _is_nan(value):
                raise QualityCheckError(f"{column} contains null values")


def check_row_count_in_range(df: Any, min_rows: int, max_rows: int) -> None:
    row_count = len(df)
    if row_count < min_rows or row_count > max_rows:
        raise QualityCheckError(f"row count {row_count} outside expected range [{min_rows}, {max_rows}]")


def _column_values(df: Any, column: str) -> Iterable[Any]:
    try:
        return cast(Iterable[Any], df[column])
    except Exception as exc:
        raise QualityCheckError(f"missing required column: {column}") from exc


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return cast(date, value.date())
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    if hasattr(value, "date"):
        return cast(date, value.date())
    raise QualityCheckError(f"cannot interpret value as date: {value!r}")


def _is_nan(value: Any) -> bool:
    return bool(value != value)


__all__ = [
    "QualityCheckError",
    "check_monotonic_time",
    "check_no_future_dates",
    "check_no_nulls_in_required",
    "check_row_count_in_range",
]
