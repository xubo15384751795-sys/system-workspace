#!/usr/bin/env python3
"""One-shot migrate Data/caselab_context/embeddings.json -> LanceDB."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from caselab_context.lancedb_store import lancedb_dir, migrate_payload_to_lancedb

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--embeddings",
        type=Path,
        default=ROOT / "Data" / "caselab_context" / "embeddings.json",
    )
    args = parser.parse_args()
    if not args.embeddings.exists():
        print(f"missing {args.embeddings}")
        return 1
    payload = json.loads(args.embeddings.read_text(encoding="utf-8"))
    count = migrate_payload_to_lancedb(payload, db_path=lancedb_dir(ROOT))
    print(f"migrated {count} docs -> {lancedb_dir(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
