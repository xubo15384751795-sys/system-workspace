from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from harvester.core.observation import observation_coverage_from_frame

logger = logging.getLogger(__name__)


def build_quality_report(
    dataset_id: str,
    df: pd.DataFrame,
    *,
    as_of_date: str,
    time_col: str = "date",
    required_columns: list[str] | None = None,
    allow_empty: bool = False,
    provider_outcome: dict[str, Any] | None = None,
    data_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []
    observation_coverage: dict[str, Any] | None = None

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

    # Pandera shape check when available (additive; does not replace blockers).
    if required and not missing_columns:
        try:
            import pandera.pandas as pa

            schema = pa.DataFrameSchema(
                {column: pa.Column(nullable=True) for column in required},
                strict=False,
                coerce=False,
            )
            schema.validate(df, lazy=True)
            _record_check(checks, "pandera_required_columns", True, "ok", warnings, severity="warn")
        except ImportError:
            logger.debug("Pandera is unavailable; using built-in quality checks")
        except Exception as exc:  # noqa: BLE001
            _record_check(
                checks,
                "pandera_required_columns",
                False,
                str(exc)[:200],
                warnings,
                severity="warn",
            )

    if time_col in df.columns and not df.empty:
        dates = pd.to_datetime(df[time_col], errors="coerce")
        null_dates = int(dates.isna().sum())
        _record_check(checks, "time_parseable", null_dates == 0, f"null_dates={null_dates}", blockers)
        if dates.notna().any():
            max_date = dates.max().date()
            min_date = dates.min().date()
            if null_dates == 0:
                observation_coverage = observation_coverage_from_frame(df, time_column=time_col)
            as_of = date.fromisoformat(as_of_date[:10])
            # Allow 5-day buffer for series with future effective dates (e.g. IORB)
            future_threshold = as_of + timedelta(days=5)
            _record_check(
                checks,
                "no_future_dates",
                max_date <= future_threshold,
                f"max_date={max_date}, as_of={as_of}",
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
    report = {
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
    if observation_coverage is not None:
        report["observation_coverage"] = observation_coverage
    if provider_outcome is not None:
        report["provider_outcome"] = provider_outcome
    if data_contract is not None:
        report["data_contract"] = data_contract
    return report


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
