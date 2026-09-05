"""Security hardening — enforce code-level safety invariants.

Tests that verify the Batch 1 hardening rules:

1. No exec(open(...).read()) in root scripts — security red line
2. No legacy deformation display files in Output/current
3. HTTP calls in Framework research files are marked research_only_non_harvester
4. Architecture reality audit includes the new checks

See: governance/architecture_cleanup_decisions.md
     governance/authority_registry.yaml
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FRAMEWORK_SRC = ROOT / "packages" / "framework_v1_archive" / "src"
REGISTRY_PATH = ROOT / "governance" / "authority_registry.yaml"


# ---------------------------------------------------------------------------
# 1. No exec(open(...).read()) in root scripts
# ---------------------------------------------------------------------------

def test_no_exec_open_in_root_scripts() -> None:
    """Root scripts must not use exec(open(...).read()) — use importlib instead."""
    violations = []
    for py_file in sorted(SCRIPTS.glob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        in_docstring = False
        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            if '"exec(' in stripped or "'exec(" in stripped:
                continue
            if "exec(open(" in stripped or "exec(open (" in stripped:
                violations.append(f"{py_file.name}:{lineno}: {stripped[:100]}")
    assert not violations, (
        "Found exec(open(...)) in root scripts (security red line):\n"
        + "\n".join(violations)
    )


def test_refresh_etf_panel_uses_importlib() -> None:
    """refresh_etf_panel.py must use importlib, not exec."""
    script = SCRIPTS / "refresh_etf_panel.py"
    if not script.exists():
        pytest.skip("refresh_etf_panel.py not found")
    source = script.read_text(encoding="utf-8")
    assert "exec(open(" not in source, "refresh_etf_panel.py still uses exec(open())"
    assert "importlib" in source, "refresh_etf_panel.py doesn't use importlib"


# ---------------------------------------------------------------------------
# 2. No legacy display files in Output/current
# ---------------------------------------------------------------------------

LEGACY_DISPLAY_NAMES = {
    "latest_report.html",
    "latest_dashboard.json",
    "latest_screenshot.png",
    "latest_run",
}


def test_no_legacy_display_in_current() -> None:
    """Output/current must not contain legacy deformation display files."""
    current = ROOT / "Output" / "current"
    if not current.exists():
        pytest.skip("Output/current not found")
    found = []
    for item in current.iterdir():
        if item.name in LEGACY_DISPLAY_NAMES:
            found.append(f"{item.name} ({'symlink' if item.is_symlink() else 'dir' if item.is_dir() else 'file'})")
    assert not found, (
        "Legacy display files in Output/current — move to Output/archive/legacy_display/:\n"
        + "\n".join(found)
    )


# ---------------------------------------------------------------------------
# 3. HTTP calls in research files are marked
# ---------------------------------------------------------------------------

RESEARCH_HTTP_FILES = [
    FRAMEWORK_SRC / "benchmarks" / "historical_replay.py",
    FRAMEWORK_SRC / "research_corpus" / "providers" / "brevan_howard.py",
]


@pytest.mark.parametrize("file_path", RESEARCH_HTTP_FILES, ids=lambda p: p.name)
def test_research_http_files_marked(file_path: Path) -> None:
    """Research files with HTTP calls must be marked research_only_non_harvester."""
    if not file_path.exists():
        pytest.skip(f"{file_path.name} not found")
    source = file_path.read_text(encoding="utf-8")
    assert "research_only_non_harvester" in source, (
        f"{file_path.name} makes HTTP calls but is not marked research_only_non_harvester.\n"
        f"Add to module docstring: HTTP status: research_only_non_harvester"
    )


def test_archived_replay_entrypoint_requires_admitted_release() -> None:
    """The archived replay must not silently acquire a default provider frame."""
    entrypoint = ROOT / "packages" / "framework_v1_archive" / "scripts" / "run_historical_replay.py"
    source = entrypoint.read_text(encoding="utf-8")
    assert "HarvesterAdapter" in source
    assert "run_historical_replay(raw=raw)" in source
    assert "run_historical_replay()" not in source
    assert "Output" in source
    assert "output/historical_replay" not in source


# ---------------------------------------------------------------------------
# 4. Data authority registry has research entries
# ---------------------------------------------------------------------------

def test_data_authority_registry_has_research_entries() -> None:
    """data_authority_registry.yaml must have entries for research HTTP files."""
    if not REGISTRY_PATH.exists():
        pytest.skip("data_authority_registry.yaml not found")
    reg = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    entries = reg.get("data_sources", [])
    paths = {e.get("path", "") for e in entries}

    research_files = [
        "packages/framework_v1_archive/src/benchmarks/historical_replay.py",
        "packages/framework_v1_archive/src/research_corpus/providers/brevan_howard.py",
    ]
    missing = [f for f in research_files if not any(f in p for p in paths)]
    assert not missing, (
        "Research HTTP files missing from data_authority_registry.yaml:\n"
        + "\n".join(missing)
    )


def test_research_entries_have_correct_authority() -> None:
    """Research HTTP file entries must have authority=research_only_non_harvester."""
    if not REGISTRY_PATH.exists():
        pytest.skip("data_authority_registry.yaml not found")
    reg = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    entries = reg.get("data_sources", [])

    research_files = [
        "historical_replay.py",
        "brevan_howard.py",
    ]
    violations = []
    for entry in entries:
        path = entry.get("path", "")
        if any(f in path for f in research_files):
            auth = entry.get("authority", "")
            if auth != "research_only_non_harvester":
                violations.append(f"{path}: authority={auth!r} (expected research_only_non_harvester)")
    assert not violations, (
        "Research HTTP entries have wrong authority:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 5. Architecture audit includes new checks
# ---------------------------------------------------------------------------

ALL_EXPECTED_CHECKS = [
    "forbidden_exec_open",
    "output_current_legacy_display",
    "unmarked_http_in_framework",
    "manual_sys_path_insert",
    "legacy_deadline_countdown",
    "data_retention_policy_unapplied",
]


def test_audit_has_all_hardening_checks() -> None:
    """architecture_reality_audit.py must include all 6 hardening checks."""
    script = SCRIPTS / "commands" / "weekly" / "architecture_reality_audit.py"
    if not script.exists():
        pytest.skip("architecture_reality_audit.py not found")
    source = script.read_text(encoding="utf-8")
    missing = [c for c in ALL_EXPECTED_CHECKS if c not in source]
    assert not missing, (
        "architecture_reality_audit.py missing checks:\n" + "\n".join(missing)
    )


# ---------------------------------------------------------------------------
# 6. API security helpers
# ---------------------------------------------------------------------------

def test_api_security_module_exists() -> None:
    """Terminal API security helpers must exist in deformation-framework."""
    security = ROOT / "packages" / "framework_v1_archive" / "src" / "api" / "security.py"
    assert security.exists(), "packages/framework_v1_archive/src/api/security.py missing"
    source = security.read_text(encoding="utf-8")
    assert "assert_bind_allowed" in source
    assert "install_api_key_middleware" in source
    assert "resolve_harvester_validation" in source


# ---------------------------------------------------------------------------
# 7. Installed package boundaries
# ---------------------------------------------------------------------------

def test_workspace_imports_helper_is_retired() -> None:
    """Path-surgery compatibility helper must not return."""
    helper = SCRIPTS / "_workspace_imports.py"
    assert not helper.exists(), "_workspace_imports.py is retired; install workspace packages"


def test_no_raw_sys_path_insert_in_scripts() -> None:
    """Production scripts must import installed packages without path surgery."""
    violations = []
    for py_file in sorted(SCRIPTS.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "sys.path.insert" in stripped:
                violations.append(f"{py_file.name}:{lineno}")
    assert not violations, (
        "Scripts with raw sys.path.insert:\n"
        + "\n".join(violations)
    )


def test_domain_packages_are_importable() -> None:
    """The editable workspace exposes public domain packages."""
    __import__("workbench")
    __import__("harvester")
    __import__("system_learning")
