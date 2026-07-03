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
FRAMEWORK_SRC = ROOT / "deformation-framework" / "src"
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
        "deformation-framework/src/benchmarks/historical_replay.py",
        "deformation-framework/src/research_corpus/providers/brevan_howard.py",
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
    script = SCRIPTS / "architecture_reality_audit.py"
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
    security = ROOT / "deformation-framework" / "src" / "api" / "security.py"
    assert security.exists(), "deformation-framework/src/api/security.py missing"
    source = security.read_text(encoding="utf-8")
    assert "assert_bind_allowed" in source
    assert "install_api_key_middleware" in source
    assert "resolve_harvester_validation" in source


# ---------------------------------------------------------------------------
# 7. Workspace imports helper
# ---------------------------------------------------------------------------

EXPECTED_HELPER_FUNCTIONS = [
    "add_workbench_src",
    "add_learning_hub_src",
    "add_framework_src",
    "add_harvester_src",
    "add_root",
    "add_scripts",
]


def test_workspace_imports_helper_exists() -> None:
    """scripts/_workspace_imports.py must exist with all helper functions."""
    helper = SCRIPTS / "_workspace_imports.py"
    assert helper.exists(), "_workspace_imports.py not found in scripts/"
    source = helper.read_text(encoding="utf-8")
    missing = [f for f in EXPECTED_HELPER_FUNCTIONS if f"def {f}" not in source]
    assert not missing, (
        "_workspace_imports.py missing functions:\n" + "\n".join(missing)
    )


def test_no_raw_sys_path_insert_in_scripts() -> None:
    """Root scripts must not use raw sys.path.insert — use _workspace_imports instead."""
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
            if "sys.path.insert" in stripped and "_workspace_imports" not in stripped:
                violations.append(f"{py_file.name}:{lineno}")
    assert not violations, (
        "Scripts with raw sys.path.insert (use _workspace_imports instead):\n"
        + "\n".join(violations)
    )


def test_scripts_use_workspace_helper() -> None:
    """Scripts that need workspace imports should use _workspace_imports helper."""
    # Scripts that we know need workspace imports
    needs_helper = {
        "ask_evidence.py": "add_workbench_src",
        "bridge_replay_to_current.py": "add_workbench_src",
        "judgment_layer.py": "add_workbench_src",
        "judgment_promotion_gate.py": "add_workbench_src",
        "structural_replay_v2.py": "add_workbench_src",
    }
    for script_name, expected_func in needs_helper.items():
        script = SCRIPTS / script_name
        if not script.exists():
            continue
        source = script.read_text(encoding="utf-8")
        assert expected_func in source and "from _workspace_imports import" in source, (
            f"{script_name} should use 'from _workspace_imports import ...{expected_func}...'"
        )
