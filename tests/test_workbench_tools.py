"""Workbench tool surface contracts (hermetic / source-level).

Operator refresh + live Output builds live in test_workbench_tools_operator.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "packages" / "workbench" / "contracts"


def test_product_framework_boundary_doc_exists() -> None:
    text = (ROOT / "PRODUCT_FRAMEWORK_BOUNDARY.md").read_text(encoding="utf-8")
    assert "Product / Workbench" in text
    assert "Historical consumption (archived)" in text
    assert "Data Providers" in text
    assert "Protocols are the only coupling point" in text
    assert "Data Consumption vs Audit" in text
    assert "Secondary audit" in text
    assert "Learning Hub event / ledger / improvement queue" in text
    assert "packages/workbench/" in text


def test_openbb_secondary_audit_path_is_observe_only() -> None:
    boundary = (ROOT / "PRODUCT_FRAMEWORK_BOUNDARY.md").read_text(encoding="utf-8")
    normalized = " ".join(boundary.split())

    assert "OpenBB output **must not**" in normalized
    assert "consumed by Deformation directly" in normalized
    assert "Secondary audit" in normalized
    assert "observe-only" in normalized
    assert "Learning Hub" in normalized
    assert "must not become model input" in normalized


def test_folder_ownership_declares_tool_and_framework_roots() -> None:
    text = (ROOT / "FOLDER_OWNERSHIP.md").read_text(encoding="utf-8")
    assert "packages/workbench/" in text
    assert "packages/harvester/" in text
    assert "packages/workbench/agents/harness/" in text
    assert "packages/learning_hub/" in text
    assert "packages/workbench/contracts/workbench/" in text
    assert "packages/workbench/src/workbench/" in text
    assert "packages/framework_v1_archive/" in text
    assert "Constitution-Level Red Line" in text


def test_legacy_tool_paths_are_symlinks_into_workbench() -> None:
    harvester = ROOT / "Structural Risk Harvester"
    harness = ROOT / "Structural Research Harness"
    learning = ROOT / "System Learning Hub"
    contracts = ROOT / "contracts"
    if not all(p.exists() for p in (harvester, harness, learning, contracts)):
        pytest.skip("legacy symlink aliases not present on this checkout")
    assert harvester.is_symlink()
    assert harness.is_symlink()
    assert learning.is_symlink()
    assert contracts.is_symlink()
    assert harvester.resolve() == ROOT / "packages" / "harvester"
    assert harness.resolve() == ROOT / "packages" / "workbench" / "agents" / "harness"
    assert learning.resolve() == ROOT / "packages" / "learning_hub"
    assert contracts.resolve() == ROOT / "packages" / "workbench" / "contracts"


def test_workbench_scripts_do_not_import_framework_or_provider_packages() -> None:
    for rel in [
        "packages/workbench/src/workbench/evidence_dashboard.py",
        "packages/workbench/src/workbench/artifact_navigator.py",
        "packages/workbench/src/workbench/current.py",
        "packages/workbench/src/workbench/contract_validator.py",
        "packages/workbench/src/workbench/workspace/build_system_index.py",
        "packages/workbench/src/workbench/workspace/list_latest.py",
        "packages/workbench/src/workbench/workspace/promote_snapshot.py",
        "packages/workbench/src/workbench/workspace/system_status.py",
    ]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "from src." not in text
        assert "import src." not in text
        assert "import harvester" not in text


def test_workbench_scripts_are_thin_wrappers() -> None:
    wrappers = {
        "scripts/build_benchmark_evidence_dashboard.py": "workbench.evidence_dashboard",
        "scripts/build_artifact_navigator.py": "workbench.artifact_navigator",
        "scripts/validate_workbench_contract.py": "workbench.contract_validator",
        "scripts/promote_snapshot.py": "workbench.workspace.promote_snapshot",
        "scripts/system_status.py": "workbench.workspace.system_status",
    }
    for rel, module in wrappers.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert module in text
        assert len(text.splitlines()) <= 18


def test_refresh_output_current_is_authority_entry_point() -> None:
    text = (ROOT / "scripts" / "refresh_output_current.py").read_text(encoding="utf-8")
    assert "Refresh Output/current" in text
    assert "run_refresh_admission" in text
    assert "list_profile_steps" in text
    assert "run_registry_step" in text
    assert "refresh_current_job" in text
    assert "for step_id in profile_steps" in text


def test_build_system_index_is_authority_entry_point() -> None:
    text = (ROOT / "scripts" / "build_system_index.py").read_text(encoding="utf-8")
    assert "system index" in text.lower()
    assert "measurement_state" in text


def test_list_latest_is_authority_entry_point() -> None:
    text = (ROOT / "scripts" / "list_latest.py").read_text(encoding="utf-8")
    assert "system_index" in text or "latest.json" in text


def test_workbench_contract_examples_validate() -> None:
    commands = [
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "provider-release",
            str(CONTRACTS / "workbench" / "examples" / "minimal_provider_release"),
        ],
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "evidence-panel",
            str(
                CONTRACTS
                / "workbench"
                / "examples"
                / "minimal_provider_release"
                / "data"
                / "evidence_panel.csv"
            ),
        ],
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "model-run",
            str(CONTRACTS / "workbench" / "examples" / "minimal_framework_run" / "model_run.json"),
        ],
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "report-artifacts",
            str(
                CONTRACTS
                / "workbench"
                / "examples"
                / "minimal_framework_run"
                / "report_artifacts.json"
            ),
        ],
    ]
    for command in commands:
        subprocess.run(command, check=True, cwd=str(ROOT))
