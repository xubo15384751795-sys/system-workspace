from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_product_framework_boundary_doc_exists() -> None:
    text = (ROOT / "PRODUCT_FRAMEWORK_BOUNDARY.md").read_text(encoding="utf-8")
    assert "Product / Workbench" in text
    assert "Framework Core" in text
    assert "Data Providers" in text
    assert "Protocols are the only coupling point" in text
    assert "Data Consumption vs Audit" in text
    assert "Secondary audit" in text
    assert "Learning Hub event / ledger / improvement queue" in text
    assert "Workbench/" in text


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
    assert "Workbench/" in text
    assert "structural-risk-harvester/" in text
    assert "Workbench/agents/harness/" in text
    assert "system-learning-hub/" in text
    assert "Workbench/contracts/workbench/" in text
    assert "Workbench/src/workbench/" in text
    assert "deformation-framework/" in text
    assert "Constitution-Level Red Line" in text


def test_legacy_tool_paths_are_symlinks_into_workbench() -> None:
    harvester = ROOT / "Structural Risk Harvester"
    harness = ROOT / "Structural Research Harness"
    learning = ROOT / "System Learning Hub"
    contracts = ROOT / "contracts"
    assert harvester.is_symlink()
    assert harness.is_symlink()
    assert learning.is_symlink()
    assert contracts.is_symlink()
    assert harvester.resolve() == ROOT / "structural-risk-harvester"
    assert harness.resolve() == ROOT / "Workbench" / "agents" / "harness"
    assert learning.resolve() == ROOT / "system-learning-hub"
    assert contracts.resolve() == ROOT / "Workbench" / "contracts"


def test_benchmark_evidence_dashboard_builds() -> None:
    subprocess.run(["python3", str(ROOT / "scripts" / "build_benchmark_evidence_dashboard.py")], check=True)

    payload_path = ROOT / "Output" / "workbench" / "benchmark_evidence" / "benchmark_evidence_dashboard.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "workbench.evidence_panel.v1"
    statuses = {row["series_id"]: row["status"] for row in payload["series"]}
    assert statuses["NFCI"] == "available"
    assert statuses["VIXCLS"] == "available"
    assert "MOVE" in statuses


def test_artifact_navigator_builds_from_current() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True)
    subprocess.run(["python3", str(ROOT / "scripts" / "build_benchmark_evidence_dashboard.py")], check=True)
    subprocess.run(["python3", str(ROOT / "scripts" / "build_artifact_navigator.py")], check=True)

    payload_path = ROOT / "Output" / "workbench" / "artifacts" / "artifact_navigator.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "workbench.report_artifact.v1"
    names = {item["name"]: item for item in payload["artifacts"]}
    assert names["Current status card"]["exists"] is True
    assert names["Framework output"]["exists"] is True


def test_workbench_scripts_do_not_import_framework_or_provider_packages() -> None:
    for rel in [
        "Workbench/src/workbench/evidence_dashboard.py",
        "Workbench/src/workbench/artifact_navigator.py",
        "Workbench/src/workbench/current.py",
        "Workbench/src/workbench/contract_validator.py",
        "Workbench/src/workbench/workspace/build_system_index.py",
        "Workbench/src/workbench/workspace/list_latest.py",
        "Workbench/src/workbench/workspace/promote_snapshot.py",
        "Workbench/src/workbench/workspace/system_status.py",
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
    """refresh_output_current.py is the unified authority entry point, not a thin wrapper."""
    text = (ROOT / "scripts" / "refresh_output_current.py").read_text(encoding="utf-8")
    assert "Refresh Output/current" in text
    assert "judgment_layer" in text
    assert "promotion_gate" in text
    assert "system_index" in text
    assert "readme_first" in text


def test_build_system_index_is_authority_entry_point() -> None:
    """build_system_index.py is the unified fact source, not a thin wrapper."""
    text = (ROOT / "scripts" / "build_system_index.py").read_text(encoding="utf-8")
    assert "system index" in text.lower()
    assert "measurement_state" in text


def test_list_latest_is_authority_entry_point() -> None:
    """list_latest.py reads from unified index, not a thin wrapper."""
    text = (ROOT / "scripts" / "list_latest.py").read_text(encoding="utf-8")
    assert "system_index" in text or "latest.json" in text


def test_workbench_contract_examples_validate() -> None:
    commands = [
        [
            "python3",
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "provider-release",
            str(ROOT / "contracts" / "workbench" / "examples" / "minimal_provider_release"),
        ],
        [
            "python3",
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "evidence-panel",
            str(
                ROOT
                / "contracts"
                / "workbench"
                / "examples"
                / "minimal_provider_release"
                / "data"
                / "evidence_panel.csv"
            ),
        ],
        [
            "python3",
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "model-run",
            str(ROOT / "contracts" / "workbench" / "examples" / "minimal_framework_run" / "model_run.json"),
        ],
        [
            "python3",
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "report-artifacts",
            str(ROOT / "contracts" / "workbench" / "examples" / "minimal_framework_run" / "report_artifacts.json"),
        ],
    ]
    for command in commands:
        subprocess.run(command, check=True)


def test_current_model_run_contract_validates() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True)
    subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "validate_workbench_contract.py"),
            "model-run",
            str(ROOT / "Output" / "current" / "model_run.json"),
        ],
        check=True,
    )
