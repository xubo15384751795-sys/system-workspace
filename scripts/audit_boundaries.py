#!/usr/bin/env python3
"""Architecture boundary audit.

Checks:
  1. No hardcoded absolute paths (e.g. /Users/...)
  2. No new legacy imports from forbidden modules
  3. Runtime modules do not directly import data_sources (legacy)
  4. No silent except Exception: pass patterns
  5. data_access does not depend on UI
  6. core does not depend on runtime or ui

Usage:
  python scripts/audit_boundaries.py          # check all
  python scripts/audit_boundaries.py --strict  # exit non-zero on any finding
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "Structural Deformation Research System" / "src"
TESTS_DIR = PROJECT_ROOT / "Structural Deformation Research System" / "tests"

ALLOWED_LEGACY_IMPORTS: set[str] = {
    # Legacy adapter is the designated bridge — it is allowed to reference
    # the old module so it can wrap it.
    "data_access/legacy_adapter.py",
    # Tests that explicitly test legacy compatibility.
    # "tests/test_legacy_migration.py",  # uncomment when this file exists
}

FORBIDDEN_DIRECT_IMPORTS: dict[str, set[str]] = {
    # Module          →  Must not import from
    "runtime":           {"data.data_sources"},
    "data_access":       {"data.data_sources"},
    "core":              {"runtime", "ui"},
    "data_access":       {"ui"},
    "output":            {"ui"},
}


def scan_python_files(root: Path) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in filenames:
            if f.endswith(".py"):
                files.append(Path(dirpath) / f)
    return files


def check_hardcoded_paths(files: list[Path]) -> list[str]:
    findings = []
    for fp in files:
        rel = fp.relative_to(SRC_DIR) if SRC_DIR in fp.parents else fp
        # Skip files that contain "/Users/" as search patterns (self-referential guards)
        if fp.name in ("runtime_context.py", "test_architecture_invariants.py"):
            continue
        try:
            lines = fp.read_text().split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if '"/Users/' in stripped or "'/Users/" in stripped:
                    findings.append(f"{rel}:{i} — hardcoded absolute path")
        except Exception:
            pass
    return findings


def check_forbidden_imports(files: list[Path]) -> list[str]:
    findings = []
    for fp in files:
        rel = str(fp.relative_to(SRC_DIR))
        module_name = rel.split("/")[0] if "/" in rel else "root"

        if module_name not in FORBIDDEN_DIRECT_IMPORTS:
            continue

        forbidden_prefixes = FORBIDDEN_DIRECT_IMPORTS[module_name]
        try:
            tree = ast.parse(fp.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module is None:
                        continue
                    for prefix in forbidden_prefixes:
                        if node.module == prefix or node.module.startswith(prefix + "."):
                            findings.append(
                                f"{rel}:{node.lineno} — {module_name} imports forbidden "
                                f"module '{node.module}'"
                            )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        for prefix in forbidden_prefixes:
                            if alias.name == prefix or alias.name.startswith(prefix + "."):
                                findings.append(
                                    f"{rel}:{node.lineno} — {module_name} imports forbidden "
                                    f"module '{alias.name}'"
                                )
        except Exception:
            pass
    return findings


def check_silent_exceptions(files: list[Path]) -> list[str]:
    """Find `except Exception:` followed by `pass` with no logging."""
    findings = []
    for fp in files:
        rel = fp.relative_to(SRC_DIR) if SRC_DIR in fp.parents else fp
        # Skip legacy shim
        if fp.name == "data_sources.py" and "data" in str(rel):
            continue
        try:
            lines = fp.read_text().split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == "except Exception:":
                    # Check next 3 lines for pass and no logging
                    next_lines = "\n".join(
                        l.strip() for l in lines[i : i + 4]
                    )
                    if "pass" in next_lines and "logging" not in next_lines and "logger" not in next_lines:
                        findings.append(f"{rel}:{i + 1} — silent except Exception (no logging)")
        except Exception:
            pass
    return findings


def main() -> int:
    files = scan_python_files(SRC_DIR)
    test_files = scan_python_files(TESTS_DIR) if TESTS_DIR.is_dir() else []
    print(f"Auditing {len(files)} Python files in {SRC_DIR}")
    if test_files:
        print(f"Auditing {len(test_files)} Python files in {TESTS_DIR}")
    print()

    all_findings: dict[str, list[str]] = {}

    print("1. Hardcoded paths ...")
    findings = check_hardcoded_paths(files)
    if test_files:
        findings += check_hardcoded_paths(test_files)
    all_findings["hardcoded_paths"] = findings
    if findings:
        for f in findings:
            print(f"  ❌ {f}")
    else:
        print("  ✅ No hardcoded absolute paths found")

    print("\n2. Forbidden cross-module imports ...")
    findings = check_forbidden_imports(files)
    all_findings["forbidden_imports"] = findings
    if findings:
        for f in findings:
            print(f"  ❌ {f}")
    else:
        print("  ✅ No forbidden imports")

    print("\n3. Silent except Exception ...")
    findings = check_silent_exceptions(files)
    if test_files:
        findings += check_silent_exceptions(test_files)
    all_findings["silent_exceptions"] = findings
    if findings:
        for f in findings:
            print(f"  ⚠️  {f}")
    else:
        print("  ✅ No silent except Exception patterns")

    total = sum(len(v) for v in all_findings.values())
    print(f"\n{'='*60}")
    print(f"Total findings: {total}")

    strict = "--strict" in sys.argv
    if strict and total > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
