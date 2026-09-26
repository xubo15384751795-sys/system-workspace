"""Live trees must not import the archived Deformation ``src.*`` namespace."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LIVE_ROOTS = (
    ROOT / "tests",
    ROOT / "packages" / "workbench",
    ROOT / "packages" / "harvester",
    ROOT / "packages" / "learning_hub",
    ROOT / "packages" / "orchestration",
    ROOT / "scripts",
    ROOT / "verity",
    ROOT / "tools",
    ROOT / "system_runtime",
    ROOT / "system_cli",
)
SKIP_DIR_NAMES = {
    "__pycache__",
    ".venv",
    "build",
    "dist",
    ".egg-info",
    "structural_workbench.egg-info",
    "structural_risk_harvester.egg-info",
}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    archive_root = (ROOT / "packages" / "framework_v1_archive" / "scripts").resolve()
    for root in LIVE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIR_NAMES or part.endswith(".egg-info") for part in path.parts):
                continue
            if archive_root in path.resolve().parents or path.resolve() == archive_root:
                continue
            files.append(path)
    return files


def _src_imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "src" or alias.name.startswith("src."):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "src" or module.startswith("src."):
                found.append(module)
    return found


def test_live_trees_do_not_import_archived_src_namespace() -> None:
    violations: list[str] = []
    for path in _iter_python_files():
        imports = _src_imports(path)
        if imports:
            rel = path.relative_to(ROOT).as_posix()
            violations.append(f"{rel}: {', '.join(sorted(set(imports)))}")
    assert violations == [], "live trees imported archived src.*:\n" + "\n".join(violations)
