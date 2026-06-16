"""Collect feedback from context and preference logs."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXT_LOG = ROOT / "caselab_context" / "feedback_log.jsonl"
PREFERENCE_LOG = ROOT / "caselab_runtime" / "feedback" / "preference_dataset.jsonl"
OUTPUT = ROOT / "Data" / "caselab_runtime" / "feedback_summary.json"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def collect() -> dict:
    context_rows = _read_jsonl(CONTEXT_LOG)
    pref_rows = _read_jsonl(PREFERENCE_LOG)
    by_status: dict[str, int] = {}
    for row in context_rows:
        status = row.get("review_status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "collected_at": datetime.now(UTC).isoformat(),
        "context_feedback_count": len(context_rows),
        "preference_count": len(pref_rows),
        "context_by_status": by_status,
        "context_rows": context_rows,
        "preference_rows": pref_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect feedback logs.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    summary = collect()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps({k: v for k, v in summary.items() if k not in {"context_rows", "preference_rows"}}, indent=2))
        return
    print(
        f"Collected context={summary['context_feedback_count']} "
        f"preference={summary['preference_count']} -> {OUTPUT}"
    )


if __name__ == "__main__":
    main()
