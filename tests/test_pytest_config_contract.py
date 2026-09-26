"""Workspace pytest configuration has one authoritative root policy."""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PROJECTS = sorted((ROOT / "packages").glob("*/pyproject.toml"))
REQUIRED_MARKERS = {
    "critical_gate",
    "semantic",
    "data_boundary",
    "benchmark",
    "report",
    "governance_loop",
    "slow",
    "operator",
    "network",
    "external_repo",
}


def _module_markers(path: Path) -> set[str]:
    """Return collection markers explicitly attached in a root test module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    markers: set[str] = set()
    for node in ast.walk(tree):
        value = node.value if isinstance(node, ast.Assign) else None
        if isinstance(node, (ast.Call, ast.Attribute)):
            value = node
        if not isinstance(value, (ast.Call, ast.Attribute)):
            continue
        candidate = value.func if isinstance(value, ast.Call) else value
        if not isinstance(candidate, ast.Attribute) or candidate.attr not in REQUIRED_MARKERS:
            continue
        parent = candidate.value
        if isinstance(parent, ast.Attribute) and parent.attr == "mark":
            root = parent.value
            if isinstance(root, ast.Name) and root.id == "pytest":
                markers.add(candidate.attr)
    return markers


def test_root_pytest_policy_is_the_only_workspace_policy() -> None:
    root_project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    config = root_project["tool"]["pytest"]["ini_options"]

    assert not (ROOT / "pytest.ini").exists()
    assert {str(item).split(":", 1)[0] for item in config["markers"]} == REQUIRED_MARKERS
    assert "not operator" in config["addopts"]
    assert "not network" in config["addopts"]
    assert "not external_repo" in config["addopts"]
    assert "not slow" in config["addopts"]
    assert {"Data", "Output", "__pycache__"} <= set(config["norecursedirs"])

    for path in PACKAGE_PROJECTS:
        project = tomllib.loads(path.read_text(encoding="utf-8"))
        assert "pytest" not in project.get("tool", {}), path


def test_root_pythonpath_covers_workspace_test_imports() -> None:
    root_project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pythonpath = set(root_project["tool"]["pytest"]["ini_options"]["pythonpath"])
    assert {
        ".",
        "packages/harvester/src",
        "packages/learning_hub/src",
        "packages/workbench/src",
        "packages/orchestration",
    } <= pythonpath
    assert "packages/framework" not in pythonpath
    assert "packages/framework/src" not in pythonpath
    assert "packages/framework_v1_archive" not in pythonpath
    assert "packages/framework_v1_archive/src" not in pythonpath
    assert "scripts" not in pythonpath


def test_root_pytest_does_not_collect_archived_framework_tests() -> None:
    import subprocess
    import sys

    root_project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    config = root_project["tool"]["pytest"]["ini_options"]
    assert config["testpaths"] == ["tests"]
    assert "packages/framework_v1_archive" in set(config["norecursedirs"])
    assert "packages/framework" not in set(config["norecursedirs"])

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    collected = proc.stdout + proc.stderr
    assert "packages/framework/tests" not in collected
    assert "packages/framework_v1_archive/tests" not in collected
    assert "test_research_http_gateway.py" not in collected


def test_marker_classification_and_root_files_are_three_way_consistent() -> None:
    """The root marker surface, classification file, and test files agree."""
    classification = yaml.safe_load(
        (ROOT / "tests" / "stateful_test_classification.yaml").read_text(encoding="utf-8")
    )
    classified_operator = {
        str(item["path"])
        for item in classification.get("items", [])
        if item.get("class") == "operator_workspace"
    }
    marked_operator = {
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "tests").glob("test_*.py"))
        if "operator" in _module_markers(path)
    }
    assert marked_operator == classified_operator
    assert all((ROOT / path).is_file() for path in classified_operator)


def test_root_type_config_has_no_deleted_submodule_exclusions() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for stale in ("deformation-framework/", "Workbench/", "structural-risk-harvester/", "system-learning-hub/"):
        assert stale not in text
