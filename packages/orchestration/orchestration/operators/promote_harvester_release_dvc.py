#!/usr/bin/env python3
"""Explicit DVC pointer write for a finalized Harvester release.

Not part of daily finalize. Invoke after a local release is sealed when
recovery evidence is required. Forbidden on the daily pipeline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestration.dvc_promote import record_release_pointer
from scripts._runtime_io import ROOT, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_id")
    parser.add_argument(
        "--exports-root",
        type=Path,
        default=ROOT / "Data" / "harvester" / "exports",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON path for the sanitized operator evidence report.",
    )
    args = parser.parse_args(argv)

    exports_root = args.exports_root
    if not exports_root.is_absolute():
        exports_root = ROOT / exports_root
    result = record_release_pointer(
        exports_root=exports_root,
        release_id=args.release_id,
        root=ROOT,
    )
    if args.report is not None:
        write_json(args.report.expanduser().resolve(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    status = result.get("dvc_commit_status") or result.get("status")
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
