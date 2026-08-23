"""Structural data contracts for release-bound tables.

These checks are intentionally independent from freshness and provider
availability. A table can be fresh but structurally unsafe, or structurally
valid but stale. The release boundary must record both facts.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

import pandas as pd


DATA_CONTRACT_VIOLATION = "DATA_CONTRACT_VIOLATION"
ETF_PRE_LISTING_EXCEPTION = "ETF 上市日前无数据"
_ALLOWED_DECLARED_EXCEPTIONS = frozenset({ETF_PRE_LISTING_EXCEPTION})
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
    listing_dates: Mapping[str, object] | None = None,
    declared_exceptions: Iterable[str] | None = None,
    require_nonempty: bool = False,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """Validate the cross-asset panel shape and primary-key invariants."""
    violations: list[str] = []
    warnings: list[str] = []
    declared = sorted(
        {
            str(item).strip()
            for item in (declared_exceptions or [])
            if str(item).strip()
        }
    )
    unsupported_exceptions = sorted(
        set(declared).difference(_ALLOWED_DECLARED_EXCEPTIONS)
    )
    if unsupported_exceptions:
        violations.append(
            "unsupported_declared_exceptions:" + ",".join(unsupported_exceptions)
        )
    if ETF_PRE_LISTING_EXCEPTION in declared and not listing_dates:
        violations.append("pre_listing_exception_requires_listing_dates")

    parsed_listing_dates: dict[str, pd.Timestamp] = {}
    for symbol, value in (listing_dates or {}).items():
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            violations.append(f"unparseable_listing_date:{symbol}")
        else:
            parsed_listing_dates[str(symbol)] = pd.Timestamp(parsed)

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
    if {"open", "high", "low", "close", "volume"}.issubset(frame.columns):
        ohlcv = frame[["open", "high", "low", "close", "volume"]].apply(
            pd.to_numeric, errors="coerce"
        )
        # Exact equality of all five fields is the signature of the previous
        # close-only adapter filling missing OHLCV with close. It is a
        # fail-closed data-quality violation, not a provider warning.
        volume_equals_close = (
            ohlcv["volume"].eq(ohlcv["close"])
            & ohlcv[["open", "high", "low"]].eq(ohlcv["close"], axis=0).all(axis=1)
        )
        polluted_rows = int(volume_equals_close.sum())
        if polluted_rows:
            violations.append(f"volume_equals_close_rows:{polluted_rows}")

    coverage: dict[str, Any] = {}
    if expected_symbols is not None and "symbol" in frame.columns:
        expected = sorted({str(symbol) for symbol in expected_symbols if str(symbol).strip()})
        observed = sorted({str(symbol) for symbol in frame["symbol"].dropna().unique()})
        missing = sorted(set(expected) - set(observed))
        pre_listing_symbols: list[str] = []
        panel_end = parsed_dates.max() if not parsed_dates.empty else pd.NaT
        if (
            ETF_PRE_LISTING_EXCEPTION in declared
            and pd.notna(panel_end)
            and parsed_listing_dates
        ):
            pre_listing_symbols = sorted(
                symbol
                for symbol in missing
                if symbol in parsed_listing_dates and panel_end < parsed_listing_dates[symbol]
            )
            missing = [symbol for symbol in missing if symbol not in pre_listing_symbols]
        ratio = len(set(observed) & set(expected)) / max(1, len(expected))
        coverage = {
            "expected_count": len(expected),
            "observed_count": len(observed),
            "coverage_ratio": round(ratio, 6),
            "missing_symbols": missing,
            "pre_listing_symbols": pre_listing_symbols,
        }
        if missing:
            warnings.append(f"coverage_missing_symbols:{','.join(missing)}")

    # Pandera is additive in this wave: the adapter emits a complete,
    # serializable diagnostic result while the built-in checks remain the
    # release authority.  Promotion to an enforcing Pandera result requires a
    # separate shadow-day governance decision.
    from harvester.quality.pandera_adapter import (
        validate_cross_asset_panel_with_pandera,
    )

    pandera_report = validate_cross_asset_panel_with_pandera(frame)
    pandera_status = str(pandera_report.get("status", "unavailable"))
    if pandera_status == "failed":
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
        "declared_exceptions": declared,
        "pandera": pandera_status,
        "pandera_report": pandera_report,
    }
    if raise_on_error and violations:
        raise DataContractViolation("cross-asset panel structural contract failed", report)
    return report


__all__ = [
    "CROSS_ASSET_REQUIRED_COLUMNS",
    "DATA_CONTRACT_VIOLATION",
    "DataContractViolation",
    "ETF_PRE_LISTING_EXCEPTION",
    "validate_cross_asset_panel_contract",
]
