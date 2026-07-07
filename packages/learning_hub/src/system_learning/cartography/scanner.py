from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

PYTHON_SUFFIX = ".py"
CONFIG_SUFFIXES = {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".env", ".lock"}
DOC_SUFFIXES = {".md", ".rst", ".txt"}
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules", ".venv", "venv"}


@dataclass(frozen=True)
class FileScan:
    path: Path
    rel_path: str
    kind: str
    lines: int
    loc: int
    classes: int = 0
    functions: int = 0
    imports: tuple[str, ...] = ()
    module: str = ""
    parse_error: str = ""


def scan_project(scan_root: Path) -> list[FileScan]:
    files: list[FileScan] = []
    for path in sorted(scan_root.rglob("*")):
        if not path.is_file() or should_skip(path):
            continue
        kind = file_kind(path)
        if not kind:
            continue
        files.append(scan_file(scan_root, path, kind))
    return files


def scan_file(scan_root: Path, path: Path, kind: str) -> FileScan:
    rel_path = path.relative_to(scan_root).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.count("\n") + (1 if text else 0)
    loc = count_loc(text, kind)
    if kind != "python":
        return FileScan(path=path, rel_path=rel_path, kind=kind, lines=lines, loc=loc)

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return FileScan(path=path, rel_path=rel_path, kind=kind, lines=lines, loc=loc, module=module_name(rel_path), parse_error=str(exc))

    classes = sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    functions = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
    imports = tuple(extract_imports(tree))
    return FileScan(path=path, rel_path=rel_path, kind=kind, lines=lines, loc=loc, classes=classes, functions=functions, imports=imports, module=module_name(rel_path))


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == PYTHON_SUFFIX:
        return "python"
    if suffix in CONFIG_SUFFIXES or path.name in {"Makefile", ".gitignore"}:
        return "config"
    if suffix in DOC_SUFFIXES:
        return "docs"
    return ""


def count_loc(text: str, kind: str) -> int:
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if kind == "python" and stripped.startswith("#"):
            continue
        count += 1
    return count


def extract_imports(tree: ast.AST) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append("." * node.level + node.module)
            elif node.level:
                imports.append("." * node.level)
    return imports


def module_name(rel_path: str) -> str:
    path = Path(rel_path)
    parts = list(path.with_suffix("").parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(part.replace("-", "_").replace(" ", "_") for part in parts)
