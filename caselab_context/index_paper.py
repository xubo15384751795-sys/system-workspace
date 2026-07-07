"""Build searchable Paper index for Context Layer retrieval."""
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from caselab_context.graph_core import extract_links
from caselab_context.load_context import PAPER_ROOT

DATA_DIR = Path(__file__).resolve().parents[1] / "Data" / "caselab_context"
INDEX_PATH = DATA_DIR / "paper_index.jsonl"

SCAN_DIRS = [
    "01_Cases",
    "02_Entities",
    "03_Mechanisms",
    "04_Mappings",
    "08_Variables",
    "09_Models",
    "10_Indicators",
    "90_Admin/Context Samples",
]


def _parse_note(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
        if match:
            meta = yaml.safe_load(match.group(1)) or {}
            body = text[match.end() :]
    title = meta.get("canonical_name") or path.stem
    note_type = meta.get("type") or "note"
    tags = meta.get("tags") or []
    aliases = meta.get("aliases") or []
    quality = meta.get("quality")
    review_status = meta.get("review_status")
    links = extract_links(meta)
    return {
        "id": str(path.relative_to(PAPER_ROOT)),
        "path": str(path),
        "title": title,
        "type": note_type,
        "tags": tags,
        "aliases": aliases,
        "quality": quality,
        "review_status": review_status,
        "links": links,
        "text": f"{title}\n{body[:4000]}",
    }


def build_index() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for rel in SCAN_DIRS:
        root = PAPER_ROOT / rel
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            records.append(_parse_note(path))
    return records


def write_index(records: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_index() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    return [json.loads(line) for line in INDEX_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Index Paper notes for context retrieval.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    records = build_index()
    write_index(records)
    summary = {
        "indexed_at": datetime.now(UTC).isoformat(),
        "count": len(records),
        "index_path": str(INDEX_PATH),
    }
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return
    print(f"Indexed {summary['count']} notes -> {INDEX_PATH}")


if __name__ == "__main__":
    main()
