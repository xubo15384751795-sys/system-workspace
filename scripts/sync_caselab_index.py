#!/usr/bin/env python3
"""Sync CaseLab Paper index when the Paper world model hash changes."""
from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from _constants import TIMEOUT_LONG  # noqa: E402
from _runtime_io import ROOT, ensure_dir, load_json as _load_json  # noqa: E402


PAPER_MANIFEST = ROOT / "Data" / "paper_world_model" / "manifest.json"
INDEX_MANIFEST = ROOT / "Data" / "caselab_context" / "index_manifest.json"


def needs_reindex() -> tuple[bool, str]:
    paper = _load_json(PAPER_MANIFEST) or {}
    index = _load_json(INDEX_MANIFEST) or {}
    paper_hash = paper.get("paper_mtime_hash")
    if not paper_hash:
        return True, "paper_manifest_missing"
    if index.get("paper_mtime_hash") == paper_hash:
        return False, "index_up_to_date"
    return True, "paper_changed"


def run_reindex() -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "caselab_context.index_paper", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_LONG,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:] or "index_paper failed")

    emb = subprocess.run(
        [sys.executable, "-m", "caselab_context.build_embeddings", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=TIMEOUT_LONG,
    )
    if emb.returncode != 0:
        raise RuntimeError(emb.stderr[-500:] or "build_embeddings failed")

    paper = _load_json(PAPER_MANIFEST) or {}
    manifest = {
        "indexed_at": datetime.now(UTC).isoformat(),
        "paper_mtime_hash": paper.get("paper_mtime_hash"),
        "paper_synced_at": paper.get("synced_at"),
        "embeddings_built": True,
    }
    ensure_dir(INDEX_MANIFEST.parent)
    INDEX_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync CaseLab index when Paper changes.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    should_run, reason = needs_reindex()
    if not should_run and not args.force:
        out = {"status": "skipped", "reason": reason}
        print(json.dumps(out, indent=2) if args.json else f"Skipped: {reason}")
        return

    manifest = run_reindex()
    out = {"status": "indexed", "reason": reason, **manifest}
    print(json.dumps(out, indent=2) if args.json else f"Indexed ({reason})")


if __name__ == "__main__":
    main()
