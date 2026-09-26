"""Machine-checkable dependency and portability invariants.

The scanner is intentionally structural. It reports dependency-direction debt
without changing the business semantics of measurement, provider admission,
publication, recovery, or claim ceilings. Temporary migration debt is accepted
only when it is explicitly recorded in ``governance/architecture_contract.yaml``
with an owner, reader, target, and removal condition.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_RELATIVE = Path("governance/architecture_contract.yaml")
_OPERATOR_PATH_RE = re.compile(r"/(?:Users|Applications|Volumes|private/var)/")
_SCHEDULER_IMPORTS = ("launchd", "systemd", "plistlib")
_AUTHORITY_IMPORTS = (
    "system_runtime.publish_admission",
    "system_runtime.provider_status",
    "verity.runtime._admission_gate",
    "workbench.judgment",
)


@dataclass(frozen=True)
class ArchitectureViolation:
    rule_id: str
    path: str
    line: int
    message: str
    module: str = ""
    debt_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArchitectureReport:
    violations: tuple[ArchitectureViolation, ...]
    unregistered: tuple[ArchitectureViolation, ...]
    debt_entries: tuple[dict[str, Any], ...]

    @property
    def blocking(self) -> tuple[ArchitectureViolation, ...]:
        return self.unregistered

    @property
    def status(self) -> str:
        return "PASS" if not self.unregistered else "BLOCKED"


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root / CONTRACT_RELATIVE
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_excluded(relative: str, contract: dict[str, Any]) -> bool:
    parts = Path(relative).parts
    excluded = contract.get("special_paths", {}).get("excluded_from_production_scan", [])
    return (
        "__pycache__" in parts
        or any(
            relative == str(prefix).rstrip("/")
            or relative.startswith(str(prefix).rstrip("/") + "/")
            for prefix in excluded
        )
    )


def _iter_production_files(root: Path, contract: dict[str, Any]) -> Iterable[Path]:
    layers = contract.get("layers", {})
    roots = [
        Path(relative)
        for layer in layers.values()
        if isinstance(layer, dict)
        for relative in layer.get("roots", [])
    ]
    seen: set[Path] = set()
    for relative_root in roots:
        base = root / relative_root
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for path in candidates:
            if path in seen:
                continue
            rel = _relative(path, root)
            if path.suffix == ".py" and not _is_excluded(rel, contract):
                seen.add(path)
                yield path


def _layer_for(relative: str, contract: dict[str, Any]) -> str | None:
    normalized = relative.rstrip("/")
    matches: list[tuple[int, str]] = []
    for layer, metadata in (contract.get("layers", {}) or {}).items():
        for root in (metadata or {}).get("roots", []) or []:
            root = str(root).rstrip("/")
            if normalized == root or normalized.startswith(root + "/"):
                matches.append((len(root), layer))
    return max(matches)[1] if matches else None


def _imports(tree: ast.AST) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                continue
            result.append((module, node.lineno))
    return result


def _module_matches(imported: str, prefixes: Iterable[str]) -> bool:
    return any(imported == prefix or imported.startswith(prefix + ".") for prefix in prefixes)


def _debt_entries(contract: dict[str, Any]) -> list[dict[str, Any]]:
    entries = list((contract.get("temporary_debt") or {}).get("entries", []) or [])
    required = {"id", "rule", "paths", "owner", "migration_target", "reader", "removal_condition"}
    errors: list[str] = []
    for entry in entries:
        missing = sorted(required - set(entry))
        if missing:
            errors.append(f"{entry.get('id', '<missing id>')}: missing {', '.join(missing)}")
    frozen = int((contract.get("temporary_debt") or {}).get("frozen_count", -1))
    if frozen != len(entries):
        errors.append(f"temporary_debt frozen_count={frozen} but entries={len(entries)}")
    if errors:
        raise ValueError("invalid architecture debt ledger: " + "; ".join(errors))
    return entries


def _match_debt(violation: ArchitectureViolation, entries: list[dict[str, Any]]) -> str | None:
    for entry in entries:
        if entry.get("rule") != violation.rule_id:
            continue
        paths = [str(path).rstrip("/") for path in entry.get("paths", []) or []]
        if not any(violation.path == path or violation.path.startswith(path + "/") for path in paths):
            continue
        module_prefixes = entry.get("module_prefixes", []) or []
        if module_prefixes and not _module_matches(violation.module, module_prefixes):
            continue
        return str(entry["id"])
    return None


def _docstring_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()
    for container in ast.walk(tree):
        body = getattr(container, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            nodes.add(id(first.value))
    return nodes


def _mentions_current_surface(node: ast.AST) -> bool:
    """Return whether an expression names the live ``Output/current`` path."""
    strings = {
        value.value
        for value in ast.walk(node)
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }
    if any("Output/current" in value for value in strings):
        return True
    return "Output" in strings and "current" in strings


def _scan_file(path: Path, root: Path, contract: dict[str, Any]) -> list[ArchitectureViolation]:
    relative = _relative(path, root)
    layer = _layer_for(relative, contract)
    if layer is None:
        return []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    violations: list[ArchitectureViolation] = []
    imports = _imports(tree)

    def add(rule: str, line: int, message: str, module: str = "") -> None:
        violations.append(ArchitectureViolation(rule, relative, line, message, module))

    for imported, line in imports:
        if layer in {"domain", "orchestration", "application_runtime_adapter"} and (
            imported == "scripts" or imported.startswith("scripts.")
        ):
            add("ARCH-001", line, "live package imports scripts.*", imported)
        if layer == "core_runtime" and imported.startswith("orchestration"):
            add("ARCH-002", line, "core runtime imports orchestration", imported)
        if layer == "core_runtime" and _module_matches(
            imported,
            ("harvester", "workbench", "system_learning", "caselab_context", "caselab_runtime", "verity.cli", "system_cli"),
        ):
            add("ARCH-003", line, "core runtime imports domain/application code", imported)
        if layer == "domain" and imported.startswith("orchestration"):
            add("ARCH-004", line, "domain imports orchestration", imported)
        if layer == "domain" and any(imported == name or imported.startswith(name + ".") for name in _SCHEDULER_IMPORTS):
            add("ARCH-005", line, "domain imports scheduler implementation", imported)
        if layer == "orchestration" and relative.endswith("/schedules.py") and _module_matches(imported, _AUTHORITY_IMPORTS):
            add("ARCH-011", line, "scheduler imports business-authority implementation", imported)
        if layer in {"core_runtime", "orchestration"} and (imported == "scripts" or imported.startswith("scripts.")):
            add("ARCH-012", line, "canonical implementation imports compatibility code", imported)

    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in {"WorkspaceConfig", "RuntimeContext", "WorkspacePaths"}:
            if layer != "core_runtime":
                add("ARCH-008", node.lineno, "path context type is defined outside system_runtime")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "load_pipeline":
                if layer not in {"orchestration"} and relative != "system_runtime/pipeline.py":
                    add("ARCH-006", node.lineno, "non-orchestration code constructs a compiled execution plan", "system_runtime.pipeline")
            elif isinstance(node.func, ast.Name) and node.func.id == "open":
                if node.args and _mentions_current_surface(node.args[0]):
                    add("ARCH-007", node.lineno, "direct open of Output/current bypasses publication/runtime")
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name):
                    if node.func.value.value.id == "sys" and node.func.value.attr == "path" and node.func.attr in {"insert", "append", "extend"}:
                        add("ARCH-009", node.lineno, "production code mutates sys.path")
                if node.func.attr in {"write_text", "write_bytes"}:
                    # Inspect the receiver, not the payload.  A remediation
                    # message may mention ``Output/current`` while the write is
                    # directed through a runtime-owned path object.
                    receiver = node.func.value
                    if _mentions_current_surface(receiver):
                        add("ARCH-007", node.lineno, "direct write to Output/current bypasses publication/runtime")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if layer == "domain" and any(
                token in node.value.casefold()
                for token in ("launchd", "launchctl", "systemd", "systemctl", "plistlib")
            ):
                add("ARCH-005", node.lineno, "domain mentions scheduler implementation")
            if node.value not in {"/Users/", "/Applications/", "/Volumes/", "/private/var/"} and _OPERATOR_PATH_RE.search(node.value):
                add("ARCH-010", node.lineno, "operator-specific absolute path in production code")

    return violations


def scan_architecture(root: Path = ROOT) -> ArchitectureReport:
    contract = load_contract(root)
    entries = _debt_entries(contract)
    violations = [
        violation
        for path in _iter_production_files(root, contract)
        for violation in _scan_file(path, root, contract)
    ]
    registered: list[ArchitectureViolation] = []
    unregistered: list[ArchitectureViolation] = []
    for violation in violations:
        debt_id = _match_debt(violation, entries)
        resolved = ArchitectureViolation(**{**violation.as_dict(), "debt_id": debt_id})
        (registered if debt_id else unregistered).append(resolved)
    return ArchitectureReport(tuple(registered + unregistered), tuple(unregistered), tuple(entries))


def main(argv: list[str] | None = None) -> int:
    del argv
    report = scan_architecture()
    payload = {
        "status": report.status,
        "registered_debt_count": len(report.violations) - len(report.unregistered),
        "unregistered_violation_count": len(report.unregistered),
        "violations": [item.as_dict() for item in report.violations],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if not report.unregistered else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
