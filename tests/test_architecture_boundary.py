"""Automated architecture boundary tests.

Verifies that governance declarations match code reality.
See: governance/architecture_reality_decisions.md §10
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FRAMEWORK_SRC = ROOT / "packages" / "framework" / "src"
HARVESTER_SRC = ROOT / "packages" / "harvester" / "src"
CAPABILITY_REGISTRY = ROOT / "governance" / "capability_registry.yaml"
MODULES_MD = ROOT / "MODULES.md"


def test_capability_registry_exists() -> None:
    """governance/capability_registry.yaml must exist."""
    assert CAPABILITY_REGISTRY.exists(), "capability_registry.yaml missing"


def test_modules_md_exists() -> None:
    """MODULES.md must exist."""
    assert MODULES_MD.exists(), "MODULES.md missing"


def test_architecture_reality_decisions_exists() -> None:
    """governance/architecture_reality_decisions.md must exist."""
    path = ROOT / "governance" / "architecture_reality_decisions.md"
    assert path.exists(), "architecture_reality_decisions.md missing"


def test_capability_registry_has_paper_retain_status() -> None:
    """Capability registry must define PAPER_RETAIN status."""
    # Check the comment block mentions PAPER_RETAIN
    raw = CAPABILITY_REGISTRY.read_text(encoding="utf-8")
    assert "PAPER_RETAIN" in raw, "capability_registry.yaml missing PAPER_RETAIN status"


def test_research_terminal_is_paper_retain() -> None:
    """Research Terminal must be PAPER_RETAIN, not UNKNOWN."""
    import yaml
    data = yaml.safe_load(CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    rt = data.get("research_terminal", {})
    assert rt.get("status") == "PAPER_RETAIN", (
        f"Research Terminal status is {rt.get('status')!r}, expected PAPER_RETAIN"
    )


def test_framework_not_imported_by_harvester() -> None:
    """Harvester must not import Framework source code."""
    if not HARVESTER_SRC.exists():
        pytest.skip("Harvester source directory not found")
    framework_import_pattern = re.compile(
        r"from\s+Structural_Deformation|import\s+Structural_Deformation|"
        r"from\s+src\.core|import\s+src\.core|"
        r"from\s+src\.operators|import\s+src\.operators"
    )
    violations = []
    for py_file in HARVESTER_SRC.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if framework_import_pattern.search(line):
                rel = py_file.relative_to(HARVESTER_SRC)
                violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, "Harvester imports Framework code:\n" + "\n".join(violations)


def test_harvester_not_imported_by_framework_core() -> None:
    """Framework core must not import Harvester source code."""
    core_dirs = ["core", "operators", "diagnostics", "dynamics", "interpretation"]
    harvester_pattern = re.compile(
        r"from\s+harvester|import\s+harvester|"
        r"from\s+structural_risk_harvester|import\s+structural_risk_harvester"
    )
    violations = []
    for dir_name in core_dirs:
        dir_path = FRAMEWORK_SRC / dir_name
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(source.splitlines(), 1):
                if harvester_pattern.search(line):
                    rel = py_file.relative_to(FRAMEWORK_SRC)
                    violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, "Framework core imports Harvester code:\n" + "\n".join(violations)


def test_modules_md_references_architecture_decisions() -> None:
    """MODULES.md must reference architecture_reality_decisions.md."""
    raw = MODULES_MD.read_text(encoding="utf-8")
    assert "architecture_reality_decisions" in raw, (
        "MODULES.md does not reference architecture_reality_decisions.md"
    )


def test_capability_registry_has_audit_cadence() -> None:
    """Modules in capability registry must have audit_cadence."""
    import yaml
    data = yaml.safe_load(CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    missing = []
    for module_name, module_data in data.items():
        if not isinstance(module_data, dict):
            continue
        if "audit_cadence" not in module_data:
            missing.append(module_name)
    assert not missing, (
        "Modules missing audit_cadence: " + ", ".join(missing)
    )


def test_evidence_release_schema_in_protocols() -> None:
    """protocols/ must contain evidence_release.schema.json."""
    path = ROOT / "protocols" / "evidence_release.schema.json"
    assert path.exists(), "evidence_release.schema.json missing from protocols/"


def test_capability_registry_schema_in_governance() -> None:
    """governance/ must contain capability_registry.schema.json."""
    path = ROOT / "governance" / "capability_registry.schema.json"
    assert path.exists(), "capability_registry.schema.json missing from governance/"


def test_root_scripts_no_yfinance_import() -> None:
    """Root scripts must not import yfinance (except archive_candidates)."""
    import ast as _ast
    scripts_dir = ROOT / "scripts"
    violations = []
    for py_file in scripts_dir.glob("*.py"):
        try:
            tree = _ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in _ast.walk(tree):
            module = None
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    if alias.name == "yfinance" or alias.name.startswith("yfinance."):
                        module = alias.name
            elif isinstance(node, _ast.ImportFrom):
                if node.module and (node.module == "yfinance" or node.module.startswith("yfinance.")):
                    module = node.module
            if module:
                # Check if file is marked ARCHIVE_CANDIDATE
                header = py_file.read_text(encoding="utf-8")[:500]
                if "ARCHIVE_CANDIDATE" not in header:
                    violations.append(f"{py_file.name}:{node.lineno}: imports {module!r}")
    assert not violations, "Root scripts import yfinance (not archive_candidate):\n" + "\n".join(violations)


def test_daily_pipeline_registry_exists() -> None:
    """governance/daily_pipeline_registry.yaml must exist."""
    path = ROOT / "governance" / "daily_pipeline_registry.yaml"
    assert path.exists(), "daily_pipeline_registry.yaml missing"


def test_etf_data_path_registered() -> None:
    """etf_data_path must be registered in capability_registry.yaml."""
    import yaml
    data = yaml.safe_load(CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    assert "etf_data_path" in data, "etf_data_path missing from capability_registry.yaml"
    assert data["etf_data_path"]["status"] == "CANONICAL"


def test_scripts_constants_module_exists() -> None:
    """scripts/_constants.py must exist (centralized magic number constants)."""
    path = ROOT / "scripts" / "_constants.py"
    assert path.exists(), "_constants.py missing from scripts/"


def test_constants_module_has_core_groups() -> None:
    """_constants.py must define the core constant groups."""
    path = ROOT / "scripts" / "_constants.py"
    raw = path.read_text(encoding="utf-8")
    required_groups = [
        "CASELAB_STRONG_THRESHOLD",
        "CASELAB_USABLE_THRESHOLD",
        "TRADING_DAYS_PER_YEAR",
        "HMM_MIN_ROLLING_REFIT",
        "TIMEOUT_SHORT",
        "STRESS_DIRECTION_ELEVATED",
        "FEEDBACK_SPY_1W_DROP",
    ]
    for name in required_groups:
        assert name in raw, f"{name} missing from _constants.py"


def test_no_standalone_yfinance_in_root_scripts() -> None:
    """Root scripts must use Harvester, not yfinance directly."""
    scripts_dir = ROOT / "scripts"
    for py_file in scripts_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        raw = py_file.read_text(encoding="utf-8")[:2000]
        if "ARCHIVE_CANDIDATE" in raw:
            continue
        assert "import yfinance" not in raw, (
            f"{py_file.name} imports yfinance directly — use Harvester instead"
        )
