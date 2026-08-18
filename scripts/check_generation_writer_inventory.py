#!/usr/bin/env python3
"""Static guard for generation-owned output writers.

The report is intentionally small and machine-readable.  It inventories
first-party active-pipeline files that use the generation path API and rejects
new hard-coded writes to live compatibility surfaces.  The two legacy
publish helpers and the migration/transaction implementation are explicit
compatibility owners; they are still required to carry generation guards.

Usage:
    python3 scripts/check_generation_writer_inventory.py
    python3 scripts/check_generation_writer_inventory.py --json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT

SURFACES = ("current", "position", "judgment", "trade_decision", "trade_ledger", "quality", "system_learning")
ACTIVE_ROOTS = (
    ROOT / "scripts",
    ROOT / "packages" / "workbench" / "src" / "workbench",
    ROOT / "system_runtime",
)
EXCLUDED_PARTS = {"archive", "archives", "__pycache__"}
COMPATIBILITY_OWNERS = {
    "scripts/_current_publish.py",
    "scripts/_shadow_publish.py",
    "scripts/migrate_output_to_generations.py",
    "system_runtime/publish_transaction.py",
}
DIRECT_SURFACE = re.compile(
    r"(?:ROOT|WORKSPACE_ROOT|rio\.ROOT|output)\s*/\s*['\"](?:Output/)?['\"]\s*/\s*['\"]("
    + "|".join(SURFACES)
    + r")['\"]"
)
DIRECT_OUTPUT_SURFACE = re.compile(
    r"(?:ROOT|WORKSPACE_ROOT|rio\.ROOT)\s*/\s*['\"]Output['\"]\s*/\s*['\"]("
    + "|".join(SURFACES)
    + r")['\"]"
)


def _files() -> list[Path]:
    found: set[Path] = set()
    for base in ACTIVE_ROOTS:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if not (set(path.relative_to(ROOT).parts) & EXCLUDED_PARTS):
                found.add(path)
    return sorted(found)


def _syntax_ok(path: Path) -> bool:
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return True
    except (OSError, SyntaxError):
        return False


def build_report(root: Path = ROOT) -> dict[str, Any]:
    files = _files()
    dynamic: list[str] = []
    direct: list[dict[str, Any]] = []
    unguarded_pointer: list[str] = []

    for path in files:
        rel = str(path.relative_to(root))
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(token in source for token in ("surface_dir(", "current_dir(", "output_surface(", "PublishTransaction")):
            dynamic.append(rel)

        if rel not in COMPATIBILITY_OWNERS:
            for line_number, line in enumerate(source.splitlines(), start=1):
                if DIRECT_SURFACE.search(line) or DIRECT_OUTPUT_SURFACE.search(line):
                    # Ignore prose/comments; executable direct paths are the
                    # prohibited bypass.  The AST parse below remains the
                    # syntax gate for every file.
                    stripped = line.split("#", 1)[0].strip()
                    if stripped and not stripped.startswith(("\"\"\"", "'''")):
                        direct.append({"file": rel, "line": line_number, "source": stripped[:180]})

        if rel not in COMPATIBILITY_OWNERS:
            pointer_writer = re.search(
                r"latest_run_id\.txt[\s\S]{0,500}write_text|write_text[\s\S]{0,500}latest_run_id\.txt",
                source,
            )
            if pointer_writer and not ("SYSTEM_GENERATION_MODE" in source and "is_symlink" in source):
                unguarded_pointer.append(rel)

    syntax_failures = [str(path.relative_to(root)) for path in files if not _syntax_ok(path)]
    report = {
        "schema_version": "system.generation_writer_inventory.v1",
        "scanned_files": len(files),
        "generation_api_files": sorted(set(dynamic)),
        "compatibility_owners": sorted(COMPATIBILITY_OWNERS),
        "direct_live_surface_findings": direct,
        "unguarded_latest_pointer_writers": sorted(set(unguarded_pointer)),
        "syntax_failures": syntax_failures,
        "verdict": "PASS" if not direct and not unguarded_pointer and not syntax_failures else "BLOCK",
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Generation writer inventory: {report['verdict']} ({report['scanned_files']} files)")
        for finding in report["direct_live_surface_findings"]:
            print(f"  direct surface: {finding['file']}:{finding['line']}")
        for finding in report["unguarded_latest_pointer_writers"]:
            print(f"  latest pointer writer: {finding}")
        for finding in report["syntax_failures"]:
            print(f"  syntax failure: {finding}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
