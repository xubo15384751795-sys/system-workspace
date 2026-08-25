"""Pandera adapter for the cross-asset structural contract.

Pandera is deliberately diagnostic in this migration wave.  The existing
contract function remains the authority for PASS/WARN/BLOCK and for the sole
declared ETF pre-listing exception.  This module gives the project a stable,
serializable Pandera result so the two implementations can be compared before
any enforcement change.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

_NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume")


def _json_safe(value: Any) -> Any:
    """Convert Pandera failure-case values into JSON-safe primitives."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return str(value)


def _candidate_for_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize only the values passed to Pandera, never the source frame."""
    candidate = frame.copy()
    if "date" in candidate.columns:
        candidate["date"] = pd.to_datetime(candidate["date"], errors="coerce")
    if "symbol" in candidate.columns:
        candidate["symbol"] = candidate["symbol"].astype("string")
    for column in _NUMERIC_COLUMNS:
        if column in candidate.columns:
            candidate[column] = pd.to_numeric(
                candidate[column], errors="coerce"
            ).astype("float64")
    return candidate


def _has_unique_primary_key(frame: pd.DataFrame) -> bool:
    if not {"symbol", "date"}.issubset(frame.columns):
        return False
    return not frame.duplicated(["symbol", "date"], keep=False).any()


def _has_no_close_as_volume_flatlines(frame: pd.DataFrame) -> bool:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return True
    ohlcv = frame[list(required)].apply(pd.to_numeric, errors="coerce")
    polluted = (
        ohlcv["volume"].eq(ohlcv["close"])
        & ohlcv[["open", "high", "low"]].eq(ohlcv["close"], axis=0).all(axis=1)
    )
    return not bool(polluted.any())


def _dates_monotonic_by_symbol(frame: pd.DataFrame) -> bool:
    if not {"symbol", "date"}.issubset(frame.columns):
        return True
    parsed = pd.to_datetime(frame["date"], errors="coerce")
    ordered = frame.assign(_contract_date=parsed)
    return all(
        bool(values.is_monotonic_increasing)
        for _, values in ordered.groupby("symbol", sort=False)['_contract_date']
    )


def build_cross_asset_panel_schema(*, require_nonempty: bool = False) -> Any:
    """Build the Pandera schema without importing Pandera at module import time.

    ``require_nonempty`` mirrors the existing data-contract option.  The
    default remains permissive because an empty frame is a valid intermediate
    diagnostic input; release writers pass ``True`` when an empty candidate is
    already a contract violation.
    """
    import pandera.pandas as pa

    columns = {
        "date": pa.Column(pa.DateTime, nullable=False),
        "symbol": pa.Column(str, nullable=False),
    }
    columns.update(
        {
            column: pa.Column(float, nullable=False)
            for column in _NUMERIC_COLUMNS
            if column != "close"
        }
    )
    columns["close"] = pa.Column(
        float,
        nullable=False,
        checks=[pa.Check.gt(0, error="close must be positive")],
    )
    checks = [
        pa.Check(
            _has_unique_primary_key,
            element_wise=False,
            error="duplicate composite key: (symbol, date)",
        ),
        pa.Check(
            _has_no_close_as_volume_flatlines,
            element_wise=False,
            error="volume is copied from close for an OHLCV flatline",
        ),
        pa.Check(
            _dates_monotonic_by_symbol,
            element_wise=False,
            error="dates are not monotonic by symbol",
        ),
    ]
    if require_nonempty:
        checks.append(
            pa.Check(
                lambda value: len(value) > 0,
                element_wise=False,
                error="frame must not be empty",
            )
        )
    return pa.DataFrameSchema(
        columns,
        strict=False,
        checks=checks,
    )


def validate_cross_asset_panel_with_pandera(
    frame: pd.DataFrame,
    *,
    require_nonempty: bool = False,
) -> dict[str, Any]:
    """Return a stable diagnostic result for the Pandera panel schema."""
    try:
        import pandera.pandas as pa
    except ImportError:
        return {
            "status": "unavailable",
            "failure_count": 0,
            "failure_cases": [],
        }

    try:
        validated = build_cross_asset_panel_schema(
            require_nonempty=require_nonempty,
        ).validate(
            _candidate_for_schema(frame),
            lazy=True,
        )
        # Keep the local variable intentional: it proves validation returned a
        # DataFrame and prevents a future adapter from silently discarding it.
        del validated
        return {
            "status": "passed",
            "failure_count": 0,
            "failure_cases": [],
        }
    except pa.errors.SchemaErrors as exc:
        failure_cases = exc.failure_cases
        records = []
        if isinstance(failure_cases, pd.DataFrame):
            records = [
                {
                    str(key): _json_safe(value)
                    for key, value in record.items()
                }
                for record in failure_cases.head(100).to_dict(orient="records")
            ]
        return {
            "status": "failed",
            "failure_count": int(len(failure_cases))
            if isinstance(failure_cases, pd.DataFrame)
            else len(records),
            "failure_cases": records,
        }
    except Exception as exc:  # noqa: BLE001 - keep contract diagnostics typed
        return {
            "status": "failed",
            "failure_count": 1,
            "failure_cases": [
                {
                    "failure_type": type(exc).__name__,
                    "message": str(exc)[:500],
                }
            ],
        }


__all__ = [
    "build_cross_asset_panel_schema",
    "validate_cross_asset_panel_with_pandera",
]
