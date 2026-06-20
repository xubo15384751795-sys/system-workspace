#!/usr/bin/env python3
"""Lint Paper frontmatter for world-model directories before commit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_root, add_scripts
add_root()
add_scripts()

from caselab_context.paper_paths import paper_root  # noqa: E402
from sync_paper_world_model import (
    SCAN_DIRS,
    extract_case,
    extract_indicator,
    extract_mechanism,
    extract_trade_idea,
    extract_variable,
    parse_frontmatter,
)  # noqa: E402

EXTRACTORS = {
    "01_Cases": extract_case,
    "03_Mechanisms": extract_mechanism,
    "08_Variables": extract_variable,
    "10_Indicators": extract_indicator,
    "05_Trade-Ideas": extract_trade_idea,
}

REQUIRED_TYPES = {
    "01_Cases": "case",
    "03_Mechanisms": "mechanism",
    "08_Variables": "variable",
    "10_Indicators": "indicator",
}

VALID_REVIEW = {"approved", "needs_review", "rejected", "reviewed"}


def lint_file(path: Path, paper_dir: Path, subdir: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    rel = str(path.relative_to(paper_dir))
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [{"file": rel, "error": f"read_failed: {exc}"}]

    frontmatter, _body = parse_frontmatter(content)
    if not frontmatter and subdir in REQUIRED_TYPES:
        errors.append({"file": rel, "error": "missing_frontmatter"})
        return errors

    expected_type = REQUIRED_TYPES.get(subdir)
    if expected_type and frontmatter.get("type") != expected_type:
        errors.append(
            {
                "file": rel,
                "error": f"type_must_be_{expected_type}",
                "actual": frontmatter.get("type"),
            }
        )

    review = str(frontmatter.get("review_status", "")).strip().lower()
    if review and review not in VALID_REVIEW:
        errors.append({"file": rel, "error": "invalid_review_status", "actual": review})

    extractor = EXTRACTORS.get(subdir)
    if extractor and frontmatter.get("type") == REQUIRED_TYPES.get(subdir):
        try:
            record = extractor(path, content, paper_dir)
            if record is None:
                errors.append({"file": rel, "error": "extractor_returned_none"})
        except Exception as exc:
            errors.append({"file": rel, "error": f"extract_failed: {exc}"})

    return errors


def lint_paper(paper_dir: Path | None = None, *, paths: list[Path] | None = None) -> list[dict[str, Any]]:
    paper_dir = paper_dir or paper_root()
    errors: list[dict[str, Any]] = []

    if paths:
        targets = paths
        for path in targets:
            if not path.exists():
                continue
            for subdir in EXTRACTORS:
                if subdir in str(path):
                    errors.extend(lint_file(path, paper_dir, subdir))
                    break
        return errors

    for subdir in EXTRACTORS:
        root = paper_dir / subdir
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            errors.extend(lint_file(path, paper_dir, subdir))
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint Paper world-model frontmatter.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("files", nargs="*", help="Optional changed files (for pre-commit).")
    args = parser.parse_args()

    paper_dir = paper_root()
    if not paper_dir.exists():
        print(f"Paper directory not found: {paper_dir}")
        sys.exit(1)

    path_args = [Path(f) for f in args.files] if args.files else None
    errors = lint_paper(paper_dir, paths=path_args)

    if args.json:
        print(json.dumps({"error_count": len(errors), "errors": errors}, indent=2))
    elif errors:
        print(f"Paper frontmatter lint failed ({len(errors)} issue(s)):")
        for item in errors[:20]:
            print(f"  - {item['file']}: {item['error']}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
