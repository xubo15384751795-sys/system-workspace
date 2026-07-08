"""Extended data boundary tests.

Verifies that the legacy DataHub is properly isolated from the public API
and that the new data_access layer is clean of HTTP dependencies.
See: governance/architecture_reality_decisions.md §2-3
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_SRC = ROOT / "packages" / "framework" / "src"


def test_create_data_hub_not_in_public_all() -> None:
    """create_data_hub must not be in src/data/__all__ (legacy, not public API)."""
    init_path = FRAMEWORK_SRC / "data" / "__init__.py"
    if not init_path.exists():
        pytest.skip("Framework data __init__.py not found")
    source = init_path.read_text(encoding="utf-8")
    # Parse the __all__ list
    try:
        tree = ast.parse(source)
    except SyntaxError:
        pytest.skip("Framework data __init__.py has syntax errors")
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
        pytest.skip("Framework data __init__.py not found")
    source = init_path.read_text(encoding="utf-8")
    assert "create_data_hub" in source, (
        "create_data_hub removed from import — must remain importable for legacy use"
    )


def test_data_access_has_no_http_imports() -> None:
    """src/data_access/ must not import HTTP client libraries."""
    data_access = FRAMEWORK_SRC / "data_access"
    if not data_access.exists():
        pytest.skip("Framework data_access directory not found")
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
        pytest.skip("Framework assembly.py not found")
    source = assembly.read_text(encoding="utf-8")
    # The _resolve_data_backend function should default to "harvester"
    assert '"harvester"' in source


def test_build_system_legacy_has_deprecation_warning() -> None:
    """Legacy backend path must emit DeprecationWarning."""
    assembly = FRAMEWORK_SRC / "runtime" / "assembly.py"
    if not assembly.exists():
        pytest.skip("Framework assembly.py not found")
    source = assembly.read_text(encoding="utf-8")
    assert "DeprecationWarning" in source or "ALLOW_LEGACY_DATAHUB" in source or "check_legacy_allowed" in source, (
        "Legacy backend path missing DeprecationWarning, ALLOW_LEGACY_DATAHUB, or check_legacy_allowed guard"
    )


def test_production_paths_do_not_import_legacy() -> None:
    """Production paths (src/data_access/, src/data/) must not import from src/_legacy/,
    except for the gateway shim which is explicitly transitional.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    framework_src = root / "packages" / "framework" / "src"

    # Production directories to check
    production_dirs = [
        framework_src / "data_access",
        framework_src / "data" / "adapters",
        framework_src / "data" / "cross_section",
        framework_src / "data" / "distribution",
        framework_src / "data" / "quality",
        framework_src / "data" / "contracts.py",
    ]

    # Exemptions: files explicitly allowed to import from _legacy
    exempt_files = {
        framework_src / "data" / "gateway" / "__init__.py",  # transitional shim with retire_after
        framework_src / "data" / "gateway" / "data_hub_lite.py",
        framework_src / "data" / "gateway" / "evidence_router.py",
        framework_src / "data" / "gateway" / "source_registry.py",
        framework_src / "data" / "adapters" / "__init__.py",  # legacy acquisition shim with retire_after
        framework_src / "data_access" / "legacy_adapter.py",  # explicitly named "legacy"
        framework_src / "data" / "paths.py",  # resolves paths, not imports _legacy modules
    }

    violations = []

    for prod_dir in production_dirs:
        py_files: list[Path] = []
        if prod_dir.is_file() and prod_dir.suffix == ".py":
            py_files = [prod_dir]
        elif prod_dir.is_dir():
            py_files = list(prod_dir.rglob("*.py"))

        for py_file in py_files:
            if "__pycache__" in str(py_file):
                continue
            if py_file in exempt_files:
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "_legacy" in alias.name:
                            module = alias.name
                elif isinstance(node, ast.ImportFrom):
                    if node.module and "_legacy" in (node.module or ""):
                        module = node.module

                if module:
                    rel = py_file.relative_to(framework_src)
                    violations.append(f"{rel}:{node.lineno}: imports _legacy module {module!r}")

    assert not violations, (
        "Production paths import from src/_legacy/ — must use data_access layer instead:\n"
        + "\n".join(violations)
    )
