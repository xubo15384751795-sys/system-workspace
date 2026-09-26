"""Read-only source/archive/install/build layout audit.

The audit verifies the contract and current symlink inventory.  It never
deletes, moves, dereferences, or rewrites a symlink or any Data/Output file.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "governance" / "layout_contract.yaml"
ALLOWED_CLASSIFICATIONS = frozenset(
    {"KEEP", "MIGRATE", "DELETE_CANDIDATE", "GENERATED", "COMPATIBILITY"}
)
RUNTIME_ROOTS = (
    ROOT / "system_runtime",
    ROOT / "verity",
    ROOT / "packages/harvester/src",
    ROOT / "packages/learning_hub/src",
    ROOT / "packages/orchestration/orchestration",
    ROOT / "packages/workbench/src",
)


def _load_contract() -> dict[str, Any]:
    document = yaml.safe_load(CONTRACT.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise ValueError("layout contract must be a mapping")
    return document


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _current_symlinks() -> dict[str, str]:
    result: dict[str, str] = {}
    for path in ROOT.rglob("*"):
        if not path.is_symlink() or any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        result[_relative(path)] = str(path.readlink())
    return result


def _python_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def _no_installed_runtime_import_from_build() -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for path in _python_files(RUNTIME_ROOTS):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            imported: str | None = None
            if isinstance(node, ast.Import):
                imported = node.names[0].name if node.names else None
            elif isinstance(node, ast.ImportFrom):
                imported = node.module
            if imported and imported.split(".", 1)[0] in {"build", "dist"}:
                violations.append(
                    {"path": _relative(path), "line": node.lineno, "import": imported}
                )
    return violations


def _no_accidental_package_tree_reads() -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    pattern = re.compile(r"(?:^|[\\\"'])((?:build|dist)/(?:packages|src|verity)/)")
    for path in _python_files(RUNTIME_ROOTS):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if pattern.search(node.value):
                violations.append(
                    {"path": _relative(path), "line": node.lineno, "value": node.value}
                )
    return violations


def _canonical_source_check(contract: dict[str, Any]) -> dict[str, Any]:
    entries = contract.get("canonical_sources") or []
    paths = [str(item.get("path", "")) for item in entries if isinstance(item, dict)]
    resolved = [(ROOT / path).resolve() for path in paths]
    missing = [path for path, resolved_path in zip(paths, resolved) if not resolved_path.exists()]
    duplicate_targets = sorted(
        {str(path) for path in resolved if resolved.count(path) > 1}
    )
    return {
        "unique_declared_paths": len(paths) == len(set(paths)),
        "unique_resolved_targets": not duplicate_targets,
        "missing": missing,
        "duplicate_targets": duplicate_targets,
    }


def build_report() -> dict[str, Any]:
    contract = _load_contract()
    current = _current_symlinks()
    entries = contract.get("symlinks") or []
    declared = {
        str(item.get("path")): item
        for item in entries
        if isinstance(item, dict) and item.get("path")
    }
    classifications = {
        path: str(item.get("classification", "")) for path, item in declared.items()
    }
    unclassified = sorted(set(current) - set(declared))
    stale_contract_entries = sorted(set(declared) - set(current))
    invalid_classifications = sorted(
        path
        for path, classification in classifications.items()
        if classification not in ALLOWED_CLASSIFICATIONS
    )
    compatibility_broken = sorted(
        path
        for path, classification in classifications.items()
        if classification == "COMPATIBILITY"
        and not (ROOT / path).resolve(strict=False).exists()
    )
    source_contract = contract.get("environments") or {}
    source_archive = source_contract.get("source_archive") or {}
    installed_runtime = source_contract.get("installed_runtime") or {}
    build_dist = source_contract.get("build_dist") or {}
    canonical = _canonical_source_check(contract)
    import_violations = _no_installed_runtime_import_from_build()
    copied_tree_violations = _no_accidental_package_tree_reads()
    gate = {
        "all_relevant_symlinks_classified": (
            "PASS"
            if not unclassified and not stale_contract_entries and not invalid_classifications
            else "FAIL"
        ),
        "source_archive_install_build_contract": (
            "PASS"
            if source_archive.get("symlink_policy")
            and installed_runtime.get("source")
            and build_dist.get("runtime_source") is False
            else "FAIL"
        ),
        "compatibility_link_resolves": "PASS" if not compatibility_broken else "FAIL",
        "canonical_source_unique": (
            "PASS"
            if canonical["unique_declared_paths"]
            and canonical["unique_resolved_targets"]
            and not canonical["missing"]
            else "FAIL"
        ),
        "no_installed_runtime_import_from_build": "PASS" if not import_violations else "FAIL",
        "no_production_read_from_accidental_copied_package_tree": (
            "PASS" if not copied_tree_violations else "FAIL"
        ),
        "no_unapproved_deletion": (
            "PASS" if contract.get("destructive_operation_performed") is False else "FAIL"
        ),
    }
    return {
        "schema_version": "governance.layout_contract_audit.v1",
        "status": "PASS" if all(value == "PASS" for value in gate.values()) else "FAIL",
        "symlink_count": len(current),
        "declared_symlink_count": len(declared),
        "gate": gate,
        "unclassified_symlinks": unclassified,
        "stale_contract_entries": stale_contract_entries,
        "invalid_classifications": invalid_classifications,
        "compatibility_broken": compatibility_broken,
        "canonical_sources": canonical,
        "runtime_build_imports": import_violations,
        "copied_package_tree_reads": copied_tree_violations,
        "classification_counts": {
            classification: sum(1 for value in classifications.values() if value == classification)
            for classification in sorted(ALLOWED_CLASSIFICATIONS)
        },
        "note": "Inventory and contract only; no symlink or Data/Output mutation was performed.",
    }


def main() -> int:
    print(json.dumps(build_report(), indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
