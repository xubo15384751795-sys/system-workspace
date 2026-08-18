"""Framework-owned architecture assertions.

The workspace audit may aggregate this result, but it must not reimplement
Framework path or import semantics.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

HTTP_MODULES = {"requests", "httpx", "aiohttp", "urllib.request", "urllib3", "urllib"}
CORE_DIRS = (
    "core",
    "operators",
    "diagnostics",
    "dynamics",
    "interpretation",
    "proxies",
    "derivation",
)
RESEARCH_DIRS = ("benchmarks", "research_corpus")
API_KEY_PATTERN = re.compile(
    r"(api_key|API_KEY|apikey|APIKEY|secret_key|SECRET_KEY)",
    re.IGNORECASE,
)


def _http_imports(directory: Path, workspace_root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for py_file in directory.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                if module in HTTP_MODULES or any(
                    module.startswith(item + ".") for item in HTTP_MODULES
                ):
                    findings.append({
                        "file": str(py_file.relative_to(workspace_root)),
                        "line": str(getattr(node, "lineno", 0)),
                        "import": module,
                    })
    return findings


def _api_key_references(directory: Path, workspace_root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for py_file in directory.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            match = API_KEY_PATTERN.search(line)
            if match:
                findings.append({
                    "file": str(py_file.relative_to(workspace_root)),
                    "line": str(lineno),
                    "match": match.group(0),
                })
    return findings


def _unmarked_research_http(
    src_root: Path,
    workspace_root: Path,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for name in RESEARCH_DIRS:
        directory = src_root / name
        if not directory.exists():
            continue
        for py_file in directory.rglob("*.py"):
            try:
                source = py_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if (
                _http_imports_for_source(source, py_file)
                and "research_only_non_harvester" not in source
            ):
                findings.append({
                    "file": str(py_file.relative_to(workspace_root)),
                    "issue": "HTTP import without research_only_non_harvester marker",
                })
    return findings


def _http_imports_for_source(source: str, path: Path) -> bool:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        if any(
            module in HTTP_MODULES
            or any(module.startswith(item + ".") for item in HTTP_MODULES)
            for module in modules
        ):
            return True
    return False


def run_framework_self_check(
    *,
    workspace_root: Path | None = None,
    src_root: Path | None = None,
) -> dict[str, Any]:
    workspace_root = (workspace_root or Path(__file__).resolve().parents[4]).resolve()
    src_root = (src_root or workspace_root / "packages" / "framework" / "src").resolve()
    http_findings: list[dict[str, str]] = []
    api_findings: list[dict[str, str]] = []
    for name in CORE_DIRS:
        directory = src_root / name
        if directory.exists():
            http_findings.extend(_http_imports(directory, workspace_root))
            api_findings.extend(_api_key_references(directory, workspace_root))
    research_findings = _unmarked_research_http(src_root, workspace_root)
    return {
        "owner": "Framework",
        "checks": {
            "framework_http_imports": http_findings,
            "framework_api_keys": api_findings,
            "unmarked_http_in_framework": research_findings,
        },
        "deviation_count": (
            len(http_findings) + len(api_findings) + len(research_findings)
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_framework_self_check()
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        for name, findings in report["checks"].items():
            for finding in findings:
                print(f"{name}: {finding}", file=sys.stderr)
    return 1 if report["deviation_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
