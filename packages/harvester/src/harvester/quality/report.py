from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

# Per-series future-date tolerance policy.
# Most series must not have dates after as_of. IORB (Interest Rate on
# Reserve Balances) is published with forward effective dates by FRED.
# The tolerance is the maximum number of days a series date may exceed
# as_of_date without triggering a no_future_dates failure.
SERIES_FUTURE_DATE_TOLERANCE: dict[str, int] = {
    "IORB": 7,  # IORB publishes effective dates up to ~7 days forward
}
DEFAULT_FUTURE_DATE_TOLERANCE = 0  # all other series: no future dates allowed


def build_quality_report(
    dataset_id: str,
    df: pd.DataFrame,
    *,
    as_of_date: str,
    time_col: str = "date",
    required_columns: list[str] | None = None,
    allow_empty: bool = False,
    series_col: str = "",
    future_date_tolerance: dict[str, int] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []

    required = required_columns or []
    _record_check(
        checks,
        "row_count_positive",
        allow_empty or len(df) > 0,
        f"rows={len(df)}, allow_empty={allow_empty}",
        blockers,
    )

    missing_columns = [column for column in required if column not in df.columns]
    _record_check(
        checks,
        "required_columns_present",
        not missing_columns,
        f"missing={missing_columns}",
        blockers,
    )

    if time_col in df.columns and not df.empty:
        dates = pd.to_datetime(df[time_col], errors="coerce")
        null_dates = int(dates.isna().sum())
        _record_check(checks, "time_parseable", null_dates == 0, f"null_dates={null_dates}", blockers)
        if dates.notna().any():
            max_date = dates.max().date()
            min_date = dates.min().date()
            as_of = date.fromisoformat(as_of_date[:10])

            # Per-series future-date check: use series_col to look up tolerance.
            # Falls back to the flat tolerance map for the whole panel.
            tolerance_map = future_date_tolerance or SERIES_FUTURE_DATE_TOLERANCE
            if series_col and series_col in df.columns:
                # Per-series: each series gets its own tolerance
                future_violations: list[str] = []
                for sid, group in df.groupby(series_col):
                    sid_str = str(sid)
                    tol = tolerance_map.get(sid_str, DEFAULT_FUTURE_DATE_TOLERANCE)
                    sid_max = pd.to_datetime(group[time_col], errors="coerce").max()
                    if sid_max is not pd.NaT:
                        sid_max_date = sid_max.date()
                        threshold = as_of + timedelta(days=tol)
                        if sid_max_date > threshold:
                            future_violations.append(
                                f"{sid_str}: max_date={sid_max_date}, tolerance=+{tol}d"
                            )
                _record_check(
                    checks,
                    "no_future_dates",
                    not future_violations,
                    f"violations={future_violations[:5]}" if future_violations
                    else f"max_date={max_date}, as_of={as_of}",
                    blockers,
                )
            else:
                # Panel-level: use the max tolerance across all series
                max_tol = max(tolerance_map.values()) if tolerance_map else DEFAULT_FUTURE_DATE_TOLERANCE
                threshold = as_of + timedelta(days=max_tol)
                _record_check(
                    checks,
                    "no_future_dates",
                    max_date <= threshold,
                    f"max_date={max_date}, as_of={as_of}, tolerance=+{max_tol}d",
                    blockers,
                )
            _record_check(
                checks,
                "time_monotonic_by_dataset_order",
                dates.dropna().is_monotonic_increasing,
                f"start={min_date}, end={max_date}",
                warnings,
                severity="warn",
            )
    elif time_col and time_col not in df.columns:
        _record_check(checks, "time_column_present", False, f"missing={time_col}", warnings, severity="warn")

    null_rates: dict[str, float] = {}
    for column in df.columns:
        if len(df) == 0:
            null_rates[column] = 0.0
        else:
            null_rates[column] = float(df[column].isna().sum() / len(df))

    status = "failed" if blockers else "warning" if warnings else "passed"
    return {
        "quality_report_version": "1.0",
        "dataset_id": dataset_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": status,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "null_rates": null_rates,
    }


def write_quality_report(report: dict[str, Any], release_dir: Path, dataset_id: str) -> Path:
    import json

    path = release_dir / "quality_reports" / f"{dataset_id}.quality.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _record_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    detail: str,
    sink: list[str],
    *,
    severity: str = "error",
) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail, "severity": severity})
    if not passed:
        sink.append(f"{name}: {detail}")


__all__ = ["build_quality_report", "write_quality_report"]
