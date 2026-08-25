#!/usr/bin/env python3
"""Create and verify the DVC pointer for the canonical DuckDB panel.

This is intentionally operator-invoked.  It tracks the already-written
``Data/canonical/panels.duckdb`` candidate and reports whether the configured
DVC remote accepted it; it is not part of ``daily_job`` until remote latency,
restoreability, and the external push boundary are approved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestration.dvc_promote import (
    record_canonical_panel_pointer,
    verify_canonical_panel_pointer,
)
from scripts._runtime_io import ROOT, write_json

DEFAULT_DATABASE = ROOT / "Data" / "canonical" / "panels.duckdb"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON path for the sanitized operator evidence report.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify pointer/workspace/remote state; never run dvc add or push.",
    )
    args = parser.parse_args(argv)

    database = args.database if args.database.is_absolute() else ROOT / args.database
    if args.verify_only:
        result = verify_canonical_panel_pointer(database_path=database, root=ROOT)
    else:
        result = record_canonical_panel_pointer(
            database_path=database,
            snapshot_id=args.snapshot_id,
            root=ROOT,
        )
    if args.report is not None:
        write_json(args.report.expanduser().resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    status = result.get("status") or result.get("dvc_commit_status")
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
