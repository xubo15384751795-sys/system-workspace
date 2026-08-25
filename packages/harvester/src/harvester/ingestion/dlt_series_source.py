"""Generic dlt shadow source for already-normalized external series.

Provider transport and parsing remain owned by Harvester.  This module starts
the dlt migration at the storage/state seam: callers provide the legacy
parser's normalized ``pandas.Series`` and dlt owns the incremental cursor,
destination state, primary key, and schema-contract policy.  It is not
imported by the default provider path until a dual-run decision promotes it.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Iterator

import dlt
import pandas as pd

SERIES_TABLE_PREFIX = "external_"
SCHEMA_CONTRACT_STRATEGIES = frozenset({"evolve", "freeze", "discard"})
DLT_MAX_ATTEMPTS = 3
DLT_BACKOFF_SECONDS = 1.0
_SERIES_COLUMNS: dict[str, Any] = {
    "date": {"data_type": "date", "nullable": False},
    "value": {"data_type": "double", "nullable": False},
}


def _table_name(series_id: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]", "_", str(series_id).strip().lower()).strip("_")
    if not value:
        raise ValueError("series_id must contain at least one identifier character")
    if value[0].isdigit():
        value = f"series_{value}"
    return f"{SERIES_TABLE_PREFIX}{value}"


def series_table_name(series_id: str) -> str:
    """Return the deterministic staging table name for a series identifier."""
    return _table_name(series_id)


def normalized_series_rows(series: pd.Series) -> tuple[dict[str, Any], ...]:
    """Convert a parsed legacy series into deterministic dlt resource rows."""
    if not isinstance(series, pd.Series):
        raise TypeError("series must be a pandas Series")
    dates = pd.to_datetime(series.index, errors="coerce")
    values = pd.to_numeric(series.to_numpy(), errors="coerce")
    frame = pd.DataFrame({"date": dates, "value": values})
    frame = frame.dropna(subset=["date", "value"]).copy()
    frame["date"] = frame["date"].dt.normalize()
    if frame["date"].duplicated().any():
        raise ValueError("normalized external series contains duplicate date keys")
    frame = frame.sort_values("date", kind="mergesort")
    return tuple(
        {
            "date": timestamp.date(),
            "value": float(value),
        }
        for timestamp, value in zip(frame["date"], frame["value"], strict=True)
    )


def run_dlt_with_retry(
    pipeline: Any,
    source_factory: Callable[[], Any],
    *,
    max_attempts: int = DLT_MAX_ATTEMPTS,
    backoff_seconds: float = DLT_BACKOFF_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[Any, int]:
    """Run a dlt source with a bounded exponential retry policy.

    ``source_factory`` is called for every attempt because a dlt source is an
    iterable execution object, not a reusable request description. Parser and
    schema errors still surface after the bounded budget and remain
    fail-closed.
    """
    if int(max_attempts) != max_attempts or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if float(backoff_seconds) < 0:
        raise ValueError("backoff_seconds must be non-negative")

    attempts = int(max_attempts)
    delay = float(backoff_seconds)
    for attempt in range(1, attempts + 1):
        try:
            return pipeline.run(source_factory()), attempt
        except Exception:
            if attempt >= attempts:
                raise
            sleep_fn(delay * (2 ** (attempt - 1)))
    raise AssertionError("unreachable dlt retry loop")


def _schema_contract(strategy: str) -> dict[str, str]:
    normalized = str(strategy).strip().lower()
    if normalized not in SCHEMA_CONTRACT_STRATEGIES:
        raise ValueError(
            f"unsupported schema contract strategy {strategy!r}; "
            f"expected one of {sorted(SCHEMA_CONTRACT_STRATEGIES)}"
        )
    # dlt 1.30 names the value-discarding mode ``discard_value``.  Keep the
    # repository-level contract vocabulary at the intended three values and
    # translate only at the adapter boundary.
    dlt_strategy = "discard_value" if normalized == "discard" else normalized
    return {"columns": dlt_strategy, "data_type": dlt_strategy}


@dlt.source(name="external_indicators_shadow")
def external_indicator_source(
    series_id: str,
    series: pd.Series,
    *,
    schema_contract: str = "freeze",
):
    """Return one incremental dlt resource for a parsed external series."""
    table_name = series_table_name(series_id)
    contract = _schema_contract(schema_contract)
    rows = normalized_series_rows(series)

    @dlt.resource(
        name=table_name,
        primary_key="date",
        write_disposition="append",
        columns=_SERIES_COLUMNS,
        schema_contract=contract,
    )
    def external_series_resource(
        incremental: dlt.sources.incremental[Any] = dlt.sources.incremental("date"),
    ) -> Iterator[dict[str, Any]]:
        last_value = incremental.last_value
        for row in rows:
            observed = row["date"]
            if last_value is not None and observed <= last_value:
                continue
            yield row

    yield external_series_resource


__all__ = [
    "DLT_BACKOFF_SECONDS",
    "DLT_MAX_ATTEMPTS",
    "SCHEMA_CONTRACT_STRATEGIES",
    "SERIES_TABLE_PREFIX",
    "external_indicator_source",
    "normalized_series_rows",
    "run_dlt_with_retry",
    "series_table_name",
]
