#!/usr/bin/env python3
"""Compare the cached CFTC payload through legacy and dlt shadow paths.

This is an operator-invoked diagnostic command.  It reads an existing JSON or
CSV payload, writes one atomic parity report, and never fetches the publisher,
updates the provider cache, or changes a release.  Run it with the optional
Harvester dependency enabled:

    uv run --project packages/harvester --extra dlt \
      python -m harvester.operators.run_cftc_dlt_shadow_parity
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from harvester.ingestion.dlt_observation import load_capture_manifest, verify_payload_digest
from harvester.ingestion.external_dlt_source import (
    SHADOW_TABLE_NAME,
    _iter_normalized_rows,
    cftc_cot_source,
    write_cftc_shadow_parity_report,
)
from harvester.ingestion.dlt_series_source import (
    DLT_BACKOFF_SECONDS,
    DLT_MAX_ATTEMPTS,
    run_dlt_with_retry,
)
from scripts._runtime_io import ROOT

DEFAULT_PAYLOAD = (
    ROOT
    / "Data"
    / "harvester"
    / "raw"
    / "external_indicators"
    / "cftc_tff_lev_sp.csv"
)
DEFAULT_OUTPUT = ROOT / "Output" / "health" / "cftc_dlt_shadow_parity.json"
DEFAULT_DATABASE = ROOT / "Output" / "health" / "cftc_dlt_shadow.duckdb"


def _read_payload(path: Path) -> str | list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        decoded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(decoded, dict):
            decoded = decoded.get("data", decoded.get("results", decoded))
        if not isinstance(decoded, list):
            raise ValueError("CFTC JSON payload must contain a row array")
        return decoded

    frame = pd.read_csv(path)
    # to_json converts numpy scalar values into ordinary JSON primitives, so
    # the legacy comparison and dlt resource receive the same row payload.
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _values_by_date(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        pd.Timestamp(row["date"]).date().isoformat(): float(row["value"])
        for row in rows
    }


def _compare_values(expected: dict[str, float], observed: dict[str, float]) -> dict[str, Any]:
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    mismatches = [
        {"date": day, "legacy": expected[day], "dlt": observed[day]}
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


def _dlt_values(database: Path) -> dict[str, float]:
    with duckdb.connect(str(database), read_only=True) as connection:
        frame = connection.sql(
            f'SELECT date, value FROM "cftc_external_shadow"."{SHADOW_TABLE_NAME}" ORDER BY date'
        ).df()
    return _values_by_date(
        [
            {"date": row.date, "value": row.value}
            for row in frame.itertuples(index=False)
        ]
    )


def _dlt_load_count(database: Path) -> int:
    with duckdb.connect(str(database), read_only=True) as connection:
        return int(
            connection.execute(
                'SELECT count(*) FROM "cftc_external_shadow"."_dlt_loads"'
            ).fetchone()[0]
        )


def run_cftc_dlt_shadow(
    payload: str | list[dict[str, Any]],
    *,
    database_path: Path | None = None,
    capture_manifest: dict[str, Any] | None = None,
    payload_path: Path | None = None,
    verify_idempotence: bool = False,
    dlt_max_attempts: int = DLT_MAX_ATTEMPTS,
    dlt_backoff_seconds: float = DLT_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """Run pure parity and, when requested, the actual dlt DuckDB shadow."""
    from harvester.ingestion.external_dlt_source import build_cftc_shadow_parity_report

    report = build_cftc_shadow_parity_report(payload)
    report.update(
        {
            "provider": "cftc",
            "schema_contract": "freeze",
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
            "capture": dict(capture_manifest) if capture_manifest is not None else None,
            "payload_digest_verified": (
                verify_payload_digest(payload_path, capture_manifest.get("payload_sha256"))
                if capture_manifest is not None and payload_path is not None
                else False
            ),
            "incremental_state": {
                "state_persisted": False,
                "idempotence_verified": False,
                "retry_policy": {
                    "max_attempts": dlt_max_attempts,
                    "backoff_seconds": dlt_backoff_seconds,
                    "strategy": "exponential",
                },
            },
        }
    )
    if database_path is None:
        return report
    if verify_idempotence and not database_path.parent.exists():
        database_path.parent.mkdir(parents=True, exist_ok=True)

    import dlt

    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    pipelines_dir = database_path.parent / "pipelines"
    pipeline = dlt.pipeline(
        pipeline_name="cftc_cot_shadow",
        dataset_name="cftc_external_shadow",
        destination=dlt.destinations.duckdb(str(database_path)),
        pipelines_dir=str(pipelines_dir),
    )
    _, initial_attempts = run_dlt_with_retry(
        pipeline,
        lambda: cftc_cot_source(payload),
        max_attempts=dlt_max_attempts,
        backoff_seconds=dlt_backoff_seconds,
    )
    expected = _values_by_date(list(_iter_normalized_rows(payload)))
    observed = _dlt_values(database_path)
    execution = _compare_values(expected, observed)
    report["dlt_execution"] = execution
    report["database_path"] = str(database_path)
    report["execution_parity"] = (
        "MATCH"
        if report.get("execution_parity") == "MATCH" and execution["status"] == "MATCH"
        else "MISMATCH"
    )
    if report["execution_parity"] != "MATCH":
        report["status"] = "MISMATCH"

    state: dict[str, Any] = {
        "state_persisted": pipelines_dir.is_dir(),
        "idempotence_verified": False,
        "retry_policy": {
            "max_attempts": dlt_max_attempts,
            "backoff_seconds": dlt_backoff_seconds,
            "strategy": "exponential",
        },
        "initial_load_attempts": initial_attempts,
    }
    if verify_idempotence:
        before = _dlt_load_count(database_path)
        _, idempotence_attempts = run_dlt_with_retry(
            pipeline,
            lambda: cftc_cot_source(payload),
            max_attempts=dlt_max_attempts,
            backoff_seconds=dlt_backoff_seconds,
        )
        after = _dlt_load_count(database_path)
        state.update(
            {
                "idempotence_verified": before == after,
                "load_count_before": before,
                "load_count_after": after,
                "idempotence_load_attempts": idempotence_attempts,
            }
        )
    report["incremental_state"] = state
    return report


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--database",
        type=Path,
        help="run the actual dlt DuckDB shadow; omitted means pure parser parity only",
    )
    parser.add_argument(
        "--capture-manifest",
        type=Path,
        help="validated provider-capture manifest; without it the report is not window-eligible",
    )
    parser.add_argument(
        "--verify-idempotence",
        action="store_true",
        help="run the same dlt resource a second time and require no new load",
    )
    parser.add_argument("--dlt-max-attempts", type=int, default=DLT_MAX_ATTEMPTS)
    parser.add_argument("--dlt-backoff-seconds", type=float, default=DLT_BACKOFF_SECONDS)
    args = parser.parse_args()

    payload_path = args.payload if args.payload.is_absolute() else ROOT / args.payload
    payload = _read_payload(payload_path)
    capture_manifest_path = args.capture_manifest
    if capture_manifest_path is None:
        candidate = payload_path.with_name(f"{payload_path.stem}.capture.json")
        if candidate.is_file():
            capture_manifest_path = candidate
    capture_manifest = (
        load_capture_manifest(
            capture_manifest_path
            if capture_manifest_path.is_absolute()
            else ROOT / capture_manifest_path,
            expected_provider="cftc",
        )
        if capture_manifest_path is not None
        else None
    )
    database_path = None
    if args.database is not None:
        database_path = args.database if args.database.is_absolute() else ROOT / args.database
    if database_path is None and args.verify_idempotence:
        parser.error("--verify-idempotence requires --database")
    if database_path is None and capture_manifest is None:
        report = write_cftc_shadow_parity_report(payload, args.output)
    else:
        report = run_cftc_dlt_shadow(
            payload,
            database_path=database_path,
            capture_manifest=capture_manifest,
            payload_path=payload_path,
            verify_idempotence=args.verify_idempotence,
            dlt_max_attempts=args.dlt_max_attempts,
            dlt_backoff_seconds=args.dlt_backoff_seconds,
        )
        output_path = args.output if args.output.is_absolute() else ROOT / args.output
        _write_json_atomically(output_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    # A mismatch is diagnostic evidence, not a scheduled pipeline failure.
    # The non-zero code makes an explicit operator invocation visible while
    # keeping this command outside the default registry path.
    return 0 if report["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
