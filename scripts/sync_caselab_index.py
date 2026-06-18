#!/usr/bin/env python3
"""Sync CaseLab Paper index when the Paper world model hash changes."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_root
add_root()
import sys

PAPER_MANIFEST = ROOT / "Data" / "paper_world_model" / "manifest.json"
INDEX_MANIFEST = ROOT / "Data" / "caselab_context" / "index_manifest.json"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:] or "index_paper failed")

    emb = subprocess.run(
        [sys.executable, "-m", "caselab_context.build_embeddings", "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
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
    INDEX_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
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
