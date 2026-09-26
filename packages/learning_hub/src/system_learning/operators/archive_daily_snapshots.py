#!/usr/bin/env python3
"""Archive daily framework and CaseLab snapshots for backfill.

Copies current artifacts into dated archive paths once per calendar day.

Usage:
    python3 scripts/archive_daily_snapshots.py
    python3 scripts/archive_daily_snapshots.py --json

Output:
    Output/archive/framework_output/YYYY-MM-DD.json
    Output/archive/caselab/YYYY-MM-DD.json
    Output/archive/snapshot_manifest.json
"""
from __future__ import annotations

import argparse
import json
import shutil

from verity.runtime.runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json

FRAMEWORK_SRC = ROOT / "Output" / "current" / "framework_output.json"
CASELAB_DIR = ROOT / "Output" / "state" / "caselab"
ARCHIVE_ROOT = ROOT / "Output" / "archive"
MANIFEST_PATH = ARCHIVE_ROOT / "snapshot_manifest.json"


def archive_daily_snapshots(date_str: str | None = None) -> dict:
    date_str = date_str or utc_now().strftime("%Y-%m-%d")
    fw_dir = ensure_dir(ARCHIVE_ROOT / "framework_output")
    cl_dir = ensure_dir(ARCHIVE_ROOT / "caselab")

    archived: list[dict[str, str]] = []
    skipped: list[str] = []

    fw_dest = fw_dir / f"{date_str}.json"
    if FRAMEWORK_SRC.exists():
        if not fw_dest.exists():
            shutil.copy2(FRAMEWORK_SRC, fw_dest)
            archived.append({"kind": "framework_output", "path": str(fw_dest)})
        else:
            skipped.append("framework_output")
    else:
        skipped.append("framework_output_missing")

    caselab_src = CASELAB_DIR / f"{date_str}.json"
    caselab_dest = cl_dir / f"{date_str}.json"
    if caselab_src.exists():
        if not caselab_dest.exists():
            shutil.copy2(caselab_src, caselab_dest)
            archived.append({"kind": "caselab", "path": str(caselab_dest)})
        else:
            skipped.append("caselab")
    else:
        skipped.append("caselab_missing")

    manifest = load_json(MANIFEST_PATH) or {"dates": {}}
    dates = dict(manifest.get("dates") or {})
    dates[date_str] = {
        "archived_at": utc_now().isoformat(),
        "archived": archived,
        "skipped": skipped,
    }
    write_json(MANIFEST_PATH, {"schema_version": "daily_snapshot_manifest.v1", "dates": dates})

    return {
        "date": date_str,
        "archived": archived,
        "skipped": skipped,
        "manifest": str(MANIFEST_PATH),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive daily framework and CaseLab snapshots.")
    parser.add_argument("--date", default=None, help="Override archive date (YYYY-MM-DD).")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = archive_daily_snapshots(args.date)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(f"Archived {len(report['archived'])} snapshot(s) for {report['date']}")
    if report["skipped"]:
        print(f"Skipped: {', '.join(report['skipped'])}")


if __name__ == "__main__":
    main()
