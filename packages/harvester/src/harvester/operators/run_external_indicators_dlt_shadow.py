#!/usr/bin/env python3
"""Run a cache-only dlt shadow load for normalized external indicators.

The legacy provider/parser remains the only acquisition route.  This command
reads its existing caches, loads the parsed series into a persistent dlt
DuckDB staging destination, and writes a parity report.  It performs no HTTP
request and is not registered in ``daily_job``.

Example:

    uv run --project packages/harvester --extra dlt \
      python -m harvester.operators.run_external_indicators_dlt_shadow
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from harvester.ingestion.dlt_series_source import (
    DLT_BACKOFF_SECONDS,
    DLT_MAX_ATTEMPTS,
    external_indicator_source,
    normalized_series_rows,
    run_dlt_with_retry,
    series_table_name,
)
from harvester.ingestion.dlt_observation import load_capture_manifest, verify_payload_digest
from harvester.providers.external_indicators import (
    KNOWN_INDICATORS,
    read_cached_external_indicator,
)
from scripts._runtime_io import ROOT

DEFAULT_CACHE_DIR = ROOT / "Data" / "harvester" / "raw" / "external_indicators"
DEFAULT_DATABASE = ROOT / "Output" / "health" / "external_indicators_dlt_shadow.duckdb"
DEFAULT_REPORT = ROOT / "Output" / "health" / "external_indicators_dlt_shadow_parity.json"


def _values_by_date(rows: tuple[dict[str, Any], ...]) -> dict[str, float]:
    return {pd.Timestamp(row["date"]).date().isoformat(): float(row["value"]) for row in rows}


def _read_dlt_values(database: Path, series_id: str) -> dict[str, float]:
    table = series_table_name(series_id)
    with duckdb.connect(str(database), read_only=True) as connection:
        frame = connection.sql(
            f'SELECT date, value FROM "external_indicators_shadow"."{table}" ORDER BY date'
        ).df()
    return _values_by_date(
        tuple(
            {"date": row.date, "value": row.value}
            for row in frame.itertuples(index=False)
        )
    )


def _compare(expected: dict[str, float], observed: dict[str, float]) -> dict[str, Any]:
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    mismatches = [
        {"date": day, "expected": expected[day], "dlt": observed[day]}
        for day in sorted(set(expected) & set(observed))
        if not math.isclose(expected[day], observed[day], rel_tol=1e-12, abs_tol=1e-12)
    ]
    return {
        "status": "MATCH" if not missing and not extra and not mismatches else "MISMATCH",
        "expected_rows": len(expected),
        "dlt_rows": len(observed),
        "missing_in_dlt": missing,
        "extra_in_dlt": extra,
        "value_mismatches": mismatches,
    }


def _dlt_load_count(database: Path) -> int:
    with duckdb.connect(str(database), read_only=True) as connection:
        return int(
            connection.execute(
                "SELECT count(*) FROM external_indicators_shadow._dlt_loads"
            ).fetchone()[0]
        )


def run_shadow(
    *,
    cache_dir: Path,
    database_path: Path,
    schema_contract: str = "freeze",
    capture_manifest: dict[str, Any] | None = None,
    verify_idempotence: bool = False,
    dlt_max_attempts: int = DLT_MAX_ATTEMPTS,
    dlt_backoff_seconds: float = DLT_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """Load available caches and compare each one to the dlt destination."""
    import dlt

    cache_dir = cache_dir.resolve()
    database_path = database_path.resolve()
    if database_path.stem == "external_indicators_shadow":
        raise ValueError(
            "external indicators dlt database filename must differ from the dataset "
            "name 'external_indicators_shadow'"
        )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline = dlt.pipeline(
        pipeline_name="external_indicators_shadow",
        dataset_name="external_indicators_shadow",
        destination=dlt.destinations.duckdb(str(database_path)),
        pipelines_dir=str(database_path.parent / "pipelines"),
    )
    series_reports: dict[str, Any] = {}
    loaded_series: list[tuple[str, pd.Series]] = []
    initial_load_attempts: dict[str, int] = {}
    idempotence_load_attempts: dict[str, int] = {}
    payload_digest_errors: list[str] = []
    payload_digest_verified = False
    payload_digests = (
        capture_manifest.get("payload_digests")
        if isinstance(capture_manifest, dict)
        else None
    )
    if not isinstance(payload_digests, dict):
        payload_digests = {}
    for indicator in KNOWN_INDICATORS:
        series = read_cached_external_indicator(indicator, cache_dir=cache_dir)
        if series is None:
            series_reports[indicator.series_id] = {
                "status": "MISSING_CACHE",
                "cache_path": str(cache_dir / f"{indicator.name.lower()}.csv"),
            }
            continue
        expected_rows = normalized_series_rows(series)
        loaded_series.append((indicator.series_id, series))
        cache_path = cache_dir / f"{indicator.name.lower()}.csv"
        expected_digest = payload_digests.get(indicator.series_id) or payload_digests.get(
            cache_path.name
        )
        if capture_manifest is not None and not verify_payload_digest(cache_path, expected_digest):
            payload_digest_errors.append(indicator.series_id)
        _, attempts = run_dlt_with_retry(
            pipeline,
            lambda: external_indicator_source(
                indicator.series_id,
                series,
                schema_contract=schema_contract,
            ),
            max_attempts=dlt_max_attempts,
            backoff_seconds=dlt_backoff_seconds,
        )
        initial_load_attempts[indicator.series_id] = attempts
        observed = _read_dlt_values(database_path, indicator.series_id)
        report = _compare(_values_by_date(expected_rows), observed)
        report["cache_path"] = str(cache_dir / f"{indicator.name.lower()}.csv")
        series_reports[indicator.series_id] = report

    if capture_manifest is not None:
        payload_digest_verified = bool(loaded_series) and not payload_digest_errors

    incremental_state: dict[str, Any] = {
        "state_persisted": (database_path.parent / "pipelines").is_dir(),
        "idempotence_verified": False,
        "retry_policy": {
            "max_attempts": dlt_max_attempts,
            "backoff_seconds": dlt_backoff_seconds,
            "strategy": "exponential",
        },
        "initial_load_attempts": initial_load_attempts,
        "idempotence_load_attempts": idempotence_load_attempts,
    }
    if verify_idempotence:
        try:
            before = _dlt_load_count(database_path)
            for series_id, series in loaded_series:
                _, attempts = run_dlt_with_retry(
                    pipeline,
                    lambda series_id=series_id, series=series: external_indicator_source(
                        series_id,
                        series,
                        schema_contract=schema_contract,
                    ),
                    max_attempts=dlt_max_attempts,
                    backoff_seconds=dlt_backoff_seconds,
                )
                idempotence_load_attempts[series_id] = attempts
            after = _dlt_load_count(database_path)
            incremental_state["idempotence_verified"] = before == after
            incremental_state["load_count_before"] = before
            incremental_state["load_count_after"] = after
        except Exception as exc:  # noqa: BLE001 - preserve operator evidence
            incremental_state["idempotence_error"] = f"{type(exc).__name__}: {exc}"

    available = [
        item for item in series_reports.values() if item.get("status") != "MISSING_CACHE"
    ]
    missing_cache = any(item.get("status") == "MISSING_CACHE" for item in series_reports.values())
    overall = "NO_DATA" if not available else "PARTIAL_MATCH" if missing_cache else "MATCH"
    if available and any(item.get("status") == "MISMATCH" for item in available):
        overall = "MISMATCH"
    report: dict[str, Any] = {
        "schema_version": "system.harvester_dlt_series_shadow.v1",
        "authority": "shadow_only",
        "status": overall,
        "generated_at": datetime.now(UTC).isoformat(),
        "observed_at": (
            str(capture_manifest["captured_at"])
            if capture_manifest is not None
            else None
        ),
        "observation_date": (
            str(capture_manifest["observation_date"])
            if capture_manifest is not None
            else None
        ),
        "provider": "external_indicators",
        "capture": dict(capture_manifest) if capture_manifest is not None else None,
        "payload_digest_verified": payload_digest_verified,
        "payload_digest_errors": payload_digest_errors,
        "database_path": str(database_path),
        "cache_dir": str(cache_dir),
        "schema_contract": schema_contract,
        "series": series_reports,
        "incremental_state": incremental_state,
        "promotion_allowed": False,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--schema-contract", choices=("evolve", "freeze", "discard"), default="freeze")
    parser.add_argument(
        "--capture-manifest",
        type=Path,
        help="validated provider-capture manifest; without it the report is cache-only",
    )
    parser.add_argument(
        "--verify-idempotence",
        action="store_true",
        help="run the same dlt resources a second time and require no new load",
    )
    parser.add_argument("--dlt-max-attempts", type=int, default=DLT_MAX_ATTEMPTS)
    parser.add_argument("--dlt-backoff-seconds", type=float, default=DLT_BACKOFF_SECONDS)
    args = parser.parse_args()
    cache_dir = args.cache_dir if args.cache_dir.is_absolute() else ROOT / args.cache_dir
    capture_manifest_path = args.capture_manifest
    if capture_manifest_path is None:
        candidate = cache_dir / "external_indicators.capture.json"
        if candidate.is_file():
            capture_manifest_path = candidate
    capture_manifest = (
        load_capture_manifest(
            capture_manifest_path
            if capture_manifest_path.is_absolute()
            else ROOT / capture_manifest_path,
            expected_provider="external_indicators",
        )
        if capture_manifest_path is not None
        else None
    )

    report = run_shadow(
        cache_dir=cache_dir,
        database_path=args.database if args.database.is_absolute() else ROOT / args.database,
        schema_contract=args.schema_contract,
        capture_manifest=capture_manifest,
        verify_idempotence=args.verify_idempotence,
        dlt_max_attempts=args.dlt_max_attempts,
        dlt_backoff_seconds=args.dlt_backoff_seconds,
    )
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
