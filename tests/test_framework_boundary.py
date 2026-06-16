"""Framework boundary enforcement tests.

Verifies that Deformation Framework source directories do not contain
HTTP client imports or API key references. These tests enforce the
principle: "Framework has no acquisition authority."
See: governance/architecture_reality_decisions.md §1
"""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_SRC = ROOT / "Structural Deformation Research System" / "src"

# Directories that must be clean of HTTP/API-key imports
CLEAN_DIRS = [
    "core",
    "operators",
    "diagnostics",
    "dynamics",
    "interpretation",
    "proxies",
    "derivation",
]

# Modules that indicate HTTP client or provider acquisition
FORBIDDEN_MODULES = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
    "urllib.request",
    "urllib.parse",
    "urllib3",
    "openbb",
    "openbb_terminal",
    "alpha_vantage",
    "polygon",
    "tiingo",
    "fred",
    "yfinance",
}

# Variable names that suggest API key usage
FORBIDDEN_VAR_PATTERNS = [
    "api_key",
    "API_KEY",
    "apikey",
    "APIKEY",
    "secret_key",
    "SECRET_KEY",
    "access_token",
    "ACCESS_TOKEN",
]


def _collect_imports(py_file: Path) -> list[tuple[str, int, str]]:
    """Return list of (module_name, line_number, import_type) from a Python file."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError):
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((alias.name, node.lineno, "import"))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                results.append((node.module, node.lineno, "from_import"))
    return results


def _collect_string_assignments(py_file: Path) -> list[tuple[str, int]]:
    """Return list of (variable_name, line_number) for string assignments."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError):
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    results.append((target.id, node.lineno))
    return results


def _scan_directory(directory: Path) -> list[str]:
    """Scan a directory for forbidden imports and API key references."""
    violations = []
    for py_file in directory.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        rel = py_file.relative_to(FRAMEWORK_SRC)

        # Check imports
        for module_name, lineno, import_type in _collect_imports(py_file):
            # Check if any forbidden module is a prefix match
            for forbidden in FORBIDDEN_MODULES:
                if module_name == forbidden or module_name.startswith(forbidden + "."):
                    violations.append(
                        f"{rel}:{lineno}: {import_type} {module_name!r} "
                        f"(forbidden in Framework {directory.name}/)"
                    )

        # Check variable names for API key patterns
        for var_name, lineno in _collect_string_assignments(py_file):
            for pattern in FORBIDDEN_VAR_PATTERNS:
                if pattern in var_name:
                    violations.append(
                        f"{rel}:{lineno}: variable {var_name!r} "
                        f"(possible API key reference in Framework {directory.name}/)"
                    )
    return violations


def test_framework_core_has_no_http_imports() -> None:
    """src/core/ must not import HTTP client libraries."""
    core = FRAMEWORK_SRC / "core"
    if not core.exists():
        return
    violations = _scan_directory(core)
    assert not violations, "HTTP/API-key violations in src/core/:\n" + "\n".join(violations)


def test_framework_operators_has_no_http_imports() -> None:
    """src/operators/ must not import HTTP client libraries."""
    ops = FRAMEWORK_SRC / "operators"
    if not ops.exists():
        return
    violations = _scan_directory(ops)
    assert not violations, "HTTP/API-key violations in src/operators/:\n" + "\n".join(violations)


def test_framework_diagnostics_has_no_http_imports() -> None:
    """src/diagnostics/ must not import HTTP client libraries."""
    diag = FRAMEWORK_SRC / "diagnostics"
    if not diag.exists():
        return
    violations = _scan_directory(diag)
    assert not violations, "HTTP/API-key violations in src/diagnostics/:\n" + "\n".join(violations)


def test_framework_dynamics_has_no_http_imports() -> None:
    """src/dynamics/ must not import HTTP client libraries."""
    dyn = FRAMEWORK_SRC / "dynamics"
    if not dyn.exists():
        return
    violations = _scan_directory(dyn)
    assert not violations, "HTTP/API-key violations in src/dynamics/:\n" + "\n".join(violations)


def test_framework_interpretation_has_no_http_imports() -> None:
    """src/interpretation/ must not import HTTP client libraries."""
    interp = FRAMEWORK_SRC / "interpretation"
    if not interp.exists():
        return
    violations = _scan_directory(interp)
    assert not violations, "HTTP/API-key violations in src/interpretation/:\n" + "\n".join(violations)


def test_framework_proxies_has_no_http_imports() -> None:
    """src/proxies/ must not import HTTP client libraries."""
    proxies = FRAMEWORK_SRC / "proxies"
    if not proxies.exists():
        return
    violations = _scan_directory(proxies)
    assert not violations, "HTTP/API-key violations in src/proxies/:\n" + "\n".join(violations)


def test_framework_derivation_has_no_http_imports() -> None:
    """src/derivation/ must not import HTTP client libraries."""
    deriv = FRAMEWORK_SRC / "derivation"
    if not deriv.exists():
        return
    violations = _scan_directory(deriv)
    assert not violations, "HTTP/API-key violations in src/derivation/:\n" + "\n".join(violations)


def test_build_system_default_backend_is_harvester() -> None:
    """build_system() must default to harvester backend."""
    assembly_file = FRAMEWORK_SRC / "runtime" / "assembly.py"
    if not assembly_file.exists():
        return
    source = assembly_file.read_text(encoding="utf-8")
    # The _resolve_data_backend function should default to "harvester"
    assert '"harvester"' in source, (
        "assembly.py does not reference 'harvester' as default backend"
    )


def test_legacy_backend_requires_explicit_opt_in() -> None:
    """Legacy backend must require explicit config or ALLOW_LEGACY_DATAHUB=1."""
    assembly_file = FRAMEWORK_SRC / "runtime" / "assembly.py"
    if not assembly_file.exists():
        return
    source = assembly_file.read_text(encoding="utf-8")
    # Must have a freeze or check mechanism
    assert "freeze_legacy_datahub" in source or "check_legacy_allowed" in source, (
        "assembly.py lacks legacy DataHub freeze/check mechanism"
    )


def test_legacy_data_sources_has_sunset_date() -> None:
    """data_sources.py must have a retire_after date."""
    ds = FRAMEWORK_SRC / "data" / "data_sources.py"
    if not ds.exists():
        return
    source = ds.read_text(encoding="utf-8")
    assert "retire_after" in source, (
        "data_sources.py lacks retire_after sunset date"
    )


def test_legacy_data_hub_has_sunset_date() -> None:
    """data_hub.py must have a retire_after date."""
    dh = FRAMEWORK_SRC / "data" / "gateway" / "data_hub.py"
    if not dh.exists():
        return
    source = dh.read_text(encoding="utf-8")
    assert "retire_after" in source, (
        "data_hub.py lacks retire_after sunset date"
    )
