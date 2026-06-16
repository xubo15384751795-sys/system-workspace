"""Build runtime paper index with schema hints."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caselab_context.index_paper import build_index, write_index
from caselab_runtime.paper_index.note_schema import required_fields

OUTPUT = ROOT / "Data" / "caselab_runtime" / "paper_index_summary.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build runtime paper index summary.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    records = build_index()
    write_index(records)
    by_type: dict[str, int] = {}
    for record in records:
        note_type = record.get("type", "note")
        by_type[note_type] = by_type.get(note_type, 0) + 1
    summary = {
        "count": len(records),
        "by_type": by_type,
        "schemas": {k: required_fields(k) for k in by_type},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(summary, indent=2))
        return
    print(f"Indexed {summary['count']} notes; summary -> {OUTPUT}")


if __name__ == "__main__":
    main()
