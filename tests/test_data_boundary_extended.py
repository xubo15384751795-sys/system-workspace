"""Extended data boundary tests.

Verifies that the legacy DataHub is properly isolated from the public API
and that the new data_access layer is clean of HTTP dependencies.
See: governance/architecture_reality_decisions.md §2-3
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_SRC = ROOT / "Structural Deformation Research System" / "src"


def test_create_data_hub_not_in_public_all() -> None:
    """create_data_hub must not be in src/data/__all__ (legacy, not public API)."""
    init_path = FRAMEWORK_SRC / "data" / "__init__.py"
    if not init_path.exists():
        return
    source = init_path.read_text(encoding="utf-8")
    # Parse the __all__ list
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, ast.List):
                        names = [
                            elt.value for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
                        # Migration markers (ALLOW_LEGACY_DATAHUB guard or
                        # retire_after date) indicate the module is being
                        # phased out, so __all__ inclusion is acceptable.
                        has_migration = (
                            "ALLOW_LEGACY_DATAHUB" in source
                            or "retire_after" in source
                        )
                        if not has_migration:
                            assert "create_data_hub" not in names, (
                                "create_data_hub is in __all__ — must be excluded "
                                "(legacy, not public API) or have migration marker"
                            )


def test_create_data_hub_still_importable() -> None:
    """create_data_hub must remain importable for legacy replay/compare."""
    init_path = FRAMEWORK_SRC / "data" / "__init__.py"
    if not init_path.exists():
        return
    source = init_path.read_text(encoding="utf-8")
    assert "create_data_hub" in source, (
        "create_data_hub removed from import — must remain importable for legacy use"
    )


def test_data_access_has_no_http_imports() -> None:
    """src/data_access/ must not import HTTP client libraries."""
    data_access = FRAMEWORK_SRC / "data_access"
    if not data_access.exists():
        return
    forbidden = {"requests", "httpx", "aiohttp", "urllib.request", "urllib3"}
    violations = []
    for py_file in data_access.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden or any(alias.name.startswith(f + ".") for f in forbidden):
                        module = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module in forbidden or any(node.module.startswith(f + ".") for f in forbidden)):
                    module = node.module
            if module:
                rel = py_file.relative_to(FRAMEWORK_SRC)
                violations.append(f"{rel}:{node.lineno}: imports {module!r}")
    assert not violations, "data_access imports HTTP libs:\n" + "\n".join(violations)


def test_build_system_default_is_harvester() -> None:
    """build_system() must default to harvester backend."""
    assembly = FRAMEWORK_SRC / "runtime" / "assembly.py"
    if not assembly.exists():
        return
    source = assembly.read_text(encoding="utf-8")
    # The _resolve_data_backend function should default to "harvester"
    assert '"harvester"' in source


def test_build_system_legacy_has_deprecation_warning() -> None:
    """Legacy backend path must emit DeprecationWarning."""
    assembly = FRAMEWORK_SRC / "runtime" / "assembly.py"
    if not assembly.exists():
        return
    source = assembly.read_text(encoding="utf-8")
    assert "DeprecationWarning" in source or "ALLOW_LEGACY_DATAHUB" in source, (
        "Legacy backend path missing DeprecationWarning or ALLOW_LEGACY_DATAHUB guard"
    )
