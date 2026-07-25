#!/usr/bin/env python3
"""Promote approved Paper inbox drafts into canonical Paper paths.

Semi-automatic merge: human sets review_status: approved on inbox drafts;
this script moves or merges them into target locations.

Usage:
    python3 scripts/promote_paper_inbox.py
    python3 scripts/promote_paper_inbox.py --dry-run
    python3 scripts/promote_paper_inbox.py --json

Output:
    Paper/40_Review/_archive/<filename>
    Output/caselab_runtime/paper_promote_report.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from caselab_context.paper_paths import paper_root
from scripts._runtime_io import ROOT, ensure_dir, utc_now, write_json

REPORT_PATH = ROOT / "Output" / "caselab_runtime" / "paper_promote_report.json"
APPROVED_STATUSES = {"approved", "reviewed", "accepted"}


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---"):
        return {}, content
    try:
        end = content.index("---", 3)
    except ValueError:
        return {}, content
    block = content[3:end].strip()
    body = content[end + 3 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line or line.startswith("  "):
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body


def _safe_target(paper_dir: Path, rel_path: str) -> Path | None:
    rel = Path(rel_path.strip().lstrip("/"))
    if ".." in rel.parts:
        return None
    target = (paper_dir / rel).resolve()
    try:
        target.relative_to(paper_dir.resolve())
    except ValueError:
        return None
    return target


def promote_inbox(
    paper_dir: Path | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    paper_dir = paper_dir or paper_root()
    inbox = paper_dir / "40_Review" / "_inbox"
    archive_dir = paper_dir / "40_Review" / "_archive"

    promoted: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    if not inbox.exists():
        return {
            "promoted_count": 0,
            "skipped_count": 0,
            "promoted": [],
            "skipped": [{"reason": "inbox_missing"}],
        }

    for path in sorted(inbox.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(content)
        status = meta.get("review_status", "needs_review").lower()
        draft_type = meta.get("type", "feedback_draft")

        if status not in APPROVED_STATUSES:
            skipped.append({"file": path.name, "reason": f"status={status}"})
            continue

        target_rel = meta.get("target_path", "").strip()
        if not target_rel:
            if draft_type == "weight_suggestion":
                target_rel = "90_Admin/Context/mechanism_calibration_notes.md"
            elif draft_type == "feedback_draft":
                target_rel = f"90_Admin/Context/feedback/{path.stem}.md"
            else:
                skipped.append({"file": path.name, "reason": "missing_target_path"})
                continue

        target = _safe_target(paper_dir, target_rel)
        if target is None:
            skipped.append({"file": path.name, "reason": "unsafe_target_path"})
            continue

        if not dry_run:
            ensure_dir(target.parent)
            if target.exists() and draft_type == "weight_suggestion":
                existing = target.read_text(encoding="utf-8")
                merged = existing.rstrip() + "\n\n---\n\n" + body
                target.write_text(merged, encoding="utf-8")
            else:
                shutil.copy2(path, target)
            ensure_dir(archive_dir)
            shutil.move(str(path), str(archive_dir / path.name))

        promoted.append({
            "file": path.name,
            "target": target_rel,
            "type": draft_type,
        })

    report = {
        "exported_at": utc_now().isoformat(),
        "paper_root": str(paper_dir),
        "dry_run": dry_run,
        "promoted_count": len(promoted),
        "skipped_count": len(skipped),
        "promoted": promoted,
        "skipped": skipped,
    }
    if not dry_run:
        write_json(REPORT_PATH, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote approved Paper inbox drafts.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paper_dir = paper_root()
    if not paper_dir.exists() and not args.dry_run:
        print(f"Paper directory not found: {paper_dir}")
        sys.exit(1)

    report = promote_inbox(paper_dir, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(f"Promoted {report['promoted_count']} draft(s), skipped {report['skipped_count']}")
    if not args.dry_run:
        print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
