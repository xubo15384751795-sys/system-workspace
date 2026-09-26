#!/usr/bin/env python3
"""Verify the default DuckDB writer and Parquet consumer boundary.

The operator consumes an existing panel, writes only to an explicitly
isolated scratch workspace through ``sync_panel_to_workspace`` (the default
writer entrypoint), reads the compatibility Parquet as a legacy consumer,
and verifies the DuckDB constraints plus the no-clobber behavior on a bad
candidate.  It never writes the repository's canonical/current surfaces and
never promotes a DVC snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from harvester.cross_asset_panel import sync_panel_to_workspace
from harvester.duckdb_panel import CANONICAL_TABLE, duckdb_canonical_panel_enabled
from verity.runtime.runtime_io import ROOT

SCHEMA_VERSION = "system.harvester_duckdb_default_path_evidence.v1"
PROMOTION_ALLOWED = False
DEFAULT_REPORT = ROOT / "Output" / "state" / "health" / "duckdb_default_path_evidence.json"
DEFAULT_PANEL = ROOT / "Data" / "harvester" / "panels" / "cross_asset_daily_panel.parquet"


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _overlaps(left: Path, right: Path) -> bool:
    left = _resolve(left)
    right = _resolve(right)
    try:
        left.relative_to(right)
        return True
    except ValueError:
        pass
    try:
        right.relative_to(left)
        return True
    except ValueError:
        return False


def _frame_digest(frame: pd.DataFrame) -> str:
    required = frame[["symbol", "date", "close"]].copy()
    required["symbol"] = required["symbol"].astype(str)
    required["date"] = pd.to_datetime(required["date"], errors="raise").dt.strftime(
        "%Y-%m-%d"
    )
    required["close"] = pd.to_numeric(required["close"], errors="raise").astype(float)
    records = required.sort_values(["symbol", "date"], kind="mergesort").to_dict(
        orient="records"
    )
    encoded = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _db_snapshot(database_path: Path) -> dict[str, Any]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        row_count, distinct_keys, minimum_close = connection.execute(
            f"SELECT count(*), count(DISTINCT (symbol, date)), min(close) FROM {CANONICAL_TABLE}"
        ).fetchone()
    return {
        "row_count": int(row_count),
        "distinct_keys": int(distinct_keys),
        "minimum_close": float(minimum_close),
        "primary_key_unique": int(row_count) == int(distinct_keys),
        "close_check_satisfied": float(minimum_close) > 0,
    }


def verify_default_path(
    *,
    input_panel: Path,
    workspace_root: Path,
    expected_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Run the default writer and compatibility consumer in isolation."""
    input_panel = _resolve(input_panel)
    workspace_root = _resolve(workspace_root)
    errors: list[str] = []
    if not input_panel.is_file():
        errors.append(f"input panel missing: {input_panel}")
    if _overlaps(workspace_root, ROOT):
        errors.append("scratch workspace must not overlap operator checkout")
    if not duckdb_canonical_panel_enabled():
        errors.append("SYSTEM_DUCKDB_CANONICAL_PANEL explicitly disables default writer")
    if errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "authority": "shadow_only",
            "promotion_allowed": PROMOTION_ALLOWED,
            "status": "BLOCKED",
            "reason": "default_path_preflight_failed",
            "errors": errors,
            "workspace_root": str(workspace_root),
            "input_panel": str(input_panel),
        }

    panel = pd.read_parquet(input_panel)
    symbols = expected_symbols or sorted(panel["symbol"].dropna().astype(str).unique())
    database_path = workspace_root / "Data" / "canonical" / "panels.duckdb"
    output = sync_panel_to_workspace(
        panel,
        workspace_root,
        expected_symbols=symbols,
    )
    source_digest = _frame_digest(panel)
    consumer_frame = pd.read_parquet(output)
    consumer_digest = _frame_digest(consumer_frame)
    before_mirror = output.read_bytes()
    before_database = database_path.read_bytes()

    invalid = panel.copy()
    invalid.loc[invalid.index[0], "close"] = 0.0
    blocked_without_clobber = False
    try:
        sync_panel_to_workspace(
            invalid,
            workspace_root,
            expected_symbols=symbols,
        )
    except (ValueError, duckdb.Error):
        blocked_without_clobber = (
            output.read_bytes() == before_mirror and database_path.read_bytes() == before_database
        )

    db_snapshot = _db_snapshot(database_path)
    consumer_shape_match = set(consumer_frame.columns) == set(panel.columns)
    consumer_row_count_match = len(consumer_frame) == len(panel)
    result = {
        "schema_version": SCHEMA_VERSION,
        "authority": "shadow_only",
        "promotion_allowed": PROMOTION_ALLOWED,
        "status": "MATCH"
        if (
            consumer_shape_match
            and consumer_row_count_match
            and source_digest == consumer_digest
            and db_snapshot["primary_key_unique"]
            and db_snapshot["close_check_satisfied"]
            and blocked_without_clobber
        )
        else "MISMATCH",
        "reason": "default_writer_consumer_constraints_match",
        "default_flag": os.environ.get("SYSTEM_DUCKDB_CANONICAL_PANEL", "<unset>"),
        "default_writer_enabled": True,
        "input_panel": str(input_panel),
        "workspace_root": str(workspace_root),
        "parquet_path": str(output),
        "database_path": str(database_path),
        "expected_symbols": symbols,
        "source_row_count": len(panel),
        "consumer_row_count": len(consumer_frame),
        "consumer_shape_match": consumer_shape_match,
        "consumer_row_count_match": consumer_row_count_match,
        "source_digest": source_digest,
        "consumer_digest": consumer_digest,
        "database": db_snapshot,
        "blocked_without_clobber": blocked_without_clobber,
        "workspace_current_touched": False,
        "dvc_promotion": False,
    }
    return result


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--expected-symbol", action="append", dest="expected_symbols")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = verify_default_path(
        input_panel=args.input_panel if args.input_panel.is_absolute() else ROOT / args.input_panel,
        workspace_root=args.workspace_root,
        expected_symbols=args.expected_symbols,
    )
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    _write_json_atomically(report_path, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
