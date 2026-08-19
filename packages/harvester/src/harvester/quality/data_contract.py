"""Structural data contracts for release-bound tables.

These checks are intentionally independent from freshness and provider
availability. A table can be fresh but structurally unsafe, or structurally
valid but stale. The release boundary must record both facts.
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd


DATA_CONTRACT_VIOLATION = "DATA_CONTRACT_VIOLATION"
CROSS_ASSET_REQUIRED_COLUMNS = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
)


class DataContractViolation(ValueError):
    """Raised when a finalized table violates a structural invariant."""

    code = DATA_CONTRACT_VIOLATION

    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(f"{DATA_CONTRACT_VIOLATION}: {message}")
        self.report = report


def validate_cross_asset_panel_contract(
    frame: pd.DataFrame,
    *,
    expected_symbols: Iterable[str] | None = None,
    require_nonempty: bool = False,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """Validate the cross-asset panel shape and primary-key invariants."""
    violations: list[str] = []
    warnings: list[str] = []
    missing_columns = [column for column in CROSS_ASSET_REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        violations.append(f"missing_columns:{','.join(missing_columns)}")
    if require_nonempty and frame.empty:
        violations.append("empty_frame")

    parsed_dates = pd.Series(dtype="datetime64[ns]")
    if "date" in frame.columns:
        parsed_dates = pd.to_datetime(frame["date"], errors="coerce")
        invalid_dates = int(parsed_dates.isna().sum())
        if invalid_dates:
            violations.append(f"unparseable_dates:{invalid_dates}")
    if "symbol" in frame.columns:
        null_symbols = int(frame["symbol"].isna().sum())
        if null_symbols:
            violations.append(f"null_symbols:{null_symbols}")
    if {"symbol", "date"}.issubset(frame.columns):
        duplicate_rows = int(frame.duplicated(["symbol", "date"], keep=False).sum())
        if duplicate_rows:
            violations.append(f"duplicate_symbol_date_rows:{duplicate_rows}")
        if not frame.empty and not parsed_dates.empty and not parsed_dates.isna().any():
            ordered = frame.assign(_contract_date=parsed_dates)
            if not ordered.groupby("symbol", sort=False)["_contract_date"].apply(
                lambda values: values.is_monotonic_increasing
            ).all():
                violations.append("dates_not_monotonic_by_symbol")

    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame.columns:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        invalid = int(numeric.isna().sum())
        if invalid:
            violations.append(f"non_numeric_{column}:{invalid}")
    if "close" in frame.columns:
        close = pd.to_numeric(frame["close"], errors="coerce")
        non_positive = int((close <= 0).sum())
        if non_positive:
            violations.append(f"non_positive_close:{non_positive}")

    coverage: dict[str, Any] = {}
    if expected_symbols is not None and "symbol" in frame.columns:
        expected = sorted({str(symbol) for symbol in expected_symbols if str(symbol).strip()})
        observed = sorted({str(symbol) for symbol in frame["symbol"].dropna().unique()})
        missing = sorted(set(expected) - set(observed))
        ratio = len(set(observed) & set(expected)) / max(1, len(expected))
        coverage = {
            "expected_count": len(expected),
            "observed_count": len(observed),
            "coverage_ratio": round(ratio, 6),
            "missing_symbols": missing,
        }
        if missing:
            warnings.append(f"coverage_missing_symbols:{','.join(missing)}")

    # Pandera is additive here: it gives the report a common engine marker
    # when installed, while the built-in checks remain the release authority.
    pandera_status = "unavailable"
    try:
        import pandera.pandas as pa

        schema = pa.DataFrameSchema(
            {
                "date": pa.Column(nullable=False),
                "symbol": pa.Column(nullable=False),
                "close": pa.Column(float, nullable=False, coerce=True),
            },
            strict=False,
            coerce=False,
        )
        schema.validate(frame, lazy=True)
        pandera_status = "passed"
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - report the typed boundary result
        pandera_status = f"failed:{str(exc)[:200]}"
        warnings.append("pandera_shape_check_failed")

    status = "BLOCK" if violations else "WARN" if warnings else "PASS"
    report: dict[str, Any] = {
        "schema_version": "system.data_contract.v1",
        "contract_id": "cross_asset_daily_panel.v1",
        "status": status,
        "error_code": DATA_CONTRACT_VIOLATION if violations else None,
        "row_count": int(len(frame)),
        "required_columns": list(CROSS_ASSET_REQUIRED_COLUMNS),
        "missing_columns": missing_columns,
        "violations": violations,
        "warnings": warnings,
        "coverage": coverage,
        "pandera": pandera_status,
    }
    if raise_on_error and violations:
        raise DataContractViolation("cross-asset panel structural contract failed", report)
    return report


__all__ = [
    "CROSS_ASSET_REQUIRED_COLUMNS",
    "DATA_CONTRACT_VIOLATION",
    "DataContractViolation",
    "validate_cross_asset_panel_contract",
]
