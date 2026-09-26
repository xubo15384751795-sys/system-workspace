#!/usr/bin/env python3
"""Archive today's HMM fit for rolling calibration history.

Copies the latest regime HMM JSON into a dated directory so
hmm_stability_audit can accumulate compatible history across daily runs
without reusing overwritten `daily/` or `latest/` pointers.

Usage:
    python3 scripts/archive_hmm_calibration_snapshot.py
    python3 scripts/archive_hmm_calibration_snapshot.py --date 2026-07-03
"""
from __future__ import annotations

import argparse
import shutil
from datetime import UTC, datetime
from pathlib import Path

from verity.runtime.runtime_io import ROOT, ensure_dir, load_json, write_json

HMM_DIR = ROOT / "Output" / "state" / "ml_signals"
HISTORY_DIR = HMM_DIR / "calibration_history"
SOURCE_CANDIDATES = (
    HMM_DIR / "latest" / "regime_hmm.json",
    HMM_DIR / "daily" / "regime_hmm.json",
)


def resolve_source() -> Path | None:
    for path in SOURCE_CANDIDATES:
        if path.is_file():
            return path
    return None


def archive_snapshot(run_date: str) -> dict[str, str | bool]:
    source = resolve_source()
    if source is None:
        return {"archived": False, "reason": "no_hmm_source", "date": run_date}

    dest_dir = HISTORY_DIR / run_date
    dest = dest_dir / "regime_hmm.json"
    if dest.exists():
        existing_mtime = dest.stat().st_mtime
        source_mtime = source.stat().st_mtime
        if source_mtime <= existing_mtime:
            return {"archived": False, "reason": "already_archived", "date": run_date, "path": str(dest)}
        # Same-day re-fit: refresh snapshot when HMM output was regenerated.

    payload = load_json(source)
    if not payload:
        return {"archived": False, "reason": "empty_source", "date": run_date}

    ensure_dir(dest_dir)
    shutil.copy2(source, dest)
    meta = {
        "schema_version": "system.hmm_calibration_snapshot.v1",
        "archived_at": datetime.now(UTC).isoformat(),
        "source": str(source.relative_to(ROOT)),
        "run_date": run_date,
        "model_signature": payload.get("stability", {}).get(
            "calibration_signature",
            payload.get("method", "unknown"),
        ),
    }
    write_json(dest_dir / "snapshot_meta.json", meta)
    return {"archived": True, "date": run_date, "path": str(dest.relative_to(ROOT))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive HMM calibration snapshot for one run day.")
    parser.add_argument(
        "--date",
        default=datetime.now(UTC).date().isoformat(),
        help="Run date folder name (YYYY-MM-DD). Defaults to UTC today.",
    )
    args = parser.parse_args()
    result = archive_snapshot(args.date)
    status = "archived" if result.get("archived") else result.get("reason", "skipped")
    print(f"HMM calibration snapshot: {status} ({result.get('date', args.date)})")
    if result.get("path"):
        print(f"  → {result['path']}")


if __name__ == "__main__":
    main()
