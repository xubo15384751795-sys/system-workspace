#!/usr/bin/env python3
"""Export System feedback drafts into Paper review inbox.

Writes markdown drafts to Paper/40_Review/_inbox/ for human merge in Obsidian.
Does not modify canonical review notes.

Usage:
    python3 scripts/export_feedback_to_paper.py
    python3 scripts/export_feedback_to_paper.py --dry-run
    python3 scripts/export_feedback_to_paper.py --force
    python3 scripts/export_feedback_to_paper.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_root
add_root()

from caselab_context.paper_paths import paper_root  # noqa: E402

CONTEXT_LOG = ROOT / "caselab_context" / "feedback_log.jsonl"
PREFERENCE_LOG = ROOT / "caselab_runtime" / "feedback" / "preference_dataset.jsonl"
OUTPUT_REPORT = ROOT / "Output" / "caselab_runtime" / "feedback_export_report.json"
STATE_PATH = ROOT / "Data" / "caselab_runtime" / "feedback_export_state.json"

EXPORT_STATUSES = {"needs_review", "rejected", "unknown"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value).strip("-")[:80]


def _content_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(row, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"entries": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"entries": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _should_export(
    state: dict[str, Any],
    key: str,
    row: dict[str, Any],
    *,
    force: bool,
) -> bool:
    if force:
        return True
    digest = _content_hash(row)
    prior = (state.get("entries") or {}).get(key)
    if prior and prior.get("content_hash") == digest:
        return False
    return True


def _render_context_draft(row: dict[str, Any]) -> str:
    feedback_id = row.get("feedback_id", "unknown")
    timestamp = row.get("timestamp", "")
    review_status = row.get("review_status", "needs_review")
    inp = row.get("input", {})
    meaning = row.get("contextual_meaning", {})

    lines = [
        "---",
        "type: feedback_draft",
        f"feedback_id: {feedback_id}",
        f"review_status: {review_status}",
        f"exported_at: {datetime.now(UTC).isoformat()}",
        "source: system/caselab_context",
        "tags:",
        "  - feedback-inbox",
        "---",
        "",
        f"# Feedback Draft: {feedback_id}",
        "",
        f"- **Exported:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Original timestamp:** {timestamp}",
        f"- **Review status:** `{review_status}`",
        "",
        "## Input",
        "",
        f"- Actor: {inp.get('actor', '')}",
        f"- Verb: {inp.get('verb', '')}",
        f"- Object: {inp.get('object', '')}",
        f"- Regime: `{json.dumps(inp.get('regime', {}), ensure_ascii=False)}`",
        "",
        "## Contextual Meaning",
        "",
        f"- Surface: {meaning.get('surface_action', '')}",
        f"- Structure: {meaning.get('deeper_structure', '')}",
        f"- Confidence: {meaning.get('confidence', '')}",
        "",
        "## Matched Rules",
        "",
    ]
    for rule in row.get("matched_rules", []):
        lines.append(f"- `{rule}`")
    lines += [
        "",
        "## Review Notes",
        "",
        row.get("review_notes") or "_Add review notes here before promoting._",
        "",
        "## Failure Reason",
        "",
        row.get("failure_reason") or "_None recorded._",
        "",
    ]
    return "\n".join(lines)


def _render_preference_draft(row: dict[str, Any], index: int) -> str:
    pref_id = row.get("preference_id") or row.get("id") or f"pref-{index:04d}"
    lines = [
        "---",
        "type: feedback_draft",
        f"feedback_id: {pref_id}",
        "review_status: needs_review",
        f"exported_at: {datetime.now(UTC).isoformat()}",
        "source: system/caselab_runtime",
        "tags:",
        "  - feedback-inbox",
        "  - preference",
        "---",
        "",
        f"# Preference Draft: {pref_id}",
        "",
        "```json",
        json.dumps(row, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    return "\n".join(lines)


def export_feedback(
    paper_dir: Path | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    paper_dir = paper_dir or paper_root()
    inbox = paper_dir / "40_Review" / "_inbox"
    exported: list[dict[str, str]] = []
    skipped_reviewed = 0
    skipped_unchanged = 0
    state = _load_state()
    entries: dict[str, Any] = dict(state.get("entries") or {})

    context_rows = _read_jsonl(CONTEXT_LOG)
    for row in context_rows:
        status = str(row.get("review_status", "unknown"))
        if status not in EXPORT_STATUSES:
            skipped_reviewed += 1
            continue
        feedback_id = str(row.get("feedback_id", "unknown"))
        key = f"context:{feedback_id}"
        if not _should_export(state, key, row, force=force):
            skipped_unchanged += 1
            continue
        filename = f"context-{_slug(feedback_id)}.md"
        target = inbox / filename
        if not dry_run:
            inbox.mkdir(parents=True, exist_ok=True)
            target.write_text(_render_context_draft(row), encoding="utf-8")
            entries[key] = {
                "content_hash": _content_hash(row),
                "exported_at": datetime.now(UTC).isoformat(),
                "path": str(target),
            }
        exported.append({"kind": "context", "feedback_id": feedback_id, "path": str(target)})

    pref_rows = _read_jsonl(PREFERENCE_LOG)
    for index, row in enumerate(pref_rows, start=1):
        pref_id = str(row.get("preference_id") or row.get("id") or f"pref-{index:04d}")
        key = f"preference:{pref_id}"
        if not _should_export(state, key, row, force=force):
            skipped_unchanged += 1
            continue
        filename = f"preference-{_slug(pref_id)}.md"
        target = inbox / filename
        if not dry_run:
            inbox.mkdir(parents=True, exist_ok=True)
            target.write_text(_render_preference_draft(row, index), encoding="utf-8")
            entries[key] = {
                "content_hash": _content_hash(row),
                "exported_at": datetime.now(UTC).isoformat(),
                "path": str(target),
            }
        exported.append({"kind": "preference", "feedback_id": pref_id, "path": str(target)})

    if not dry_run:
        _save_state({"updated_at": datetime.now(UTC).isoformat(), "entries": entries})

    report = {
        "exported_at": datetime.now(UTC).isoformat(),
        "paper_root": str(paper_dir),
        "inbox": str(inbox),
        "dry_run": dry_run,
        "force": force,
        "exported_count": len(exported),
        "skipped_reviewed_context_count": skipped_reviewed,
        "skipped_unchanged_count": skipped_unchanged,
        "exported": exported,
    }

    if not dry_run:
        OUTPUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Export feedback drafts to Paper inbox.")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing files.")
    parser.add_argument("--force", action="store_true", help="Re-export even if content unchanged.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    paper_dir = paper_root()
    if not paper_dir.exists():
        print(f"Paper directory not found: {paper_dir}")
        sys.exit(1)

    report = export_feedback(paper_dir, dry_run=args.dry_run, force=args.force)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(
        f"Exported {report['exported_count']} draft(s) to {report['inbox']} "
        f"(skipped reviewed={report['skipped_reviewed_context_count']}, "
        f"unchanged={report['skipped_unchanged_count']})"
    )
    if not args.dry_run:
        print(f"Report: {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
