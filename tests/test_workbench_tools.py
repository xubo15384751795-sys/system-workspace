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
    sandbox = (ROOT / "Output" / "sandbox" / "README.md").read_text(encoding="utf-8")
    openbb = (ROOT / "Output" / "sandbox" / "openbb" / "README.md").read_text(encoding="utf-8")

    combined = "\n".join([boundary, sandbox, openbb])
    assert "OpenBB output **must not** be consumed by Deformation directly" in combined
    assert "Secondary audit path" in combined
    assert "observe-only" in combined
    assert "Learning Hub" in combined
    assert "must not become model input" in combined


def test_folder_ownership_declares_tool_and_framework_roots() -> None:
    text = (ROOT / "FOLDER_OWNERSHIP.md").read_text(encoding="utf-8")
    assert "Workbench/" in text
    assert "Workbench/data_providers/structural-risk-harvester/" in text
    assert "Workbench/agent_harness/structural-research-harness/" in text
    assert "Workbench/governance/system-learning-hub/" in text
    assert "Workbench/contracts/workbench/" in text
    assert "Workbench/src/workbench/workspace/" in text
    assert "Structural Deformation Research System/" in text
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
    assert harvester.resolve() == ROOT / "Workbench" / "data_providers" / "structural-risk-harvester"
    assert harness.resolve() == ROOT / "Workbench" / "agent_harness" / "structural-research-harness"
    assert learning.resolve() == ROOT / "Workbench" / "governance" / "system-learning-hub"
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
    assert names["Latest HTML report"]["exists"] is True
    assert names["Benchmark evidence dashboard"]["exists"] is True


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
        "scripts/refresh_output_current.py": "workbench.current",
        "scripts/validate_workbench_contract.py": "workbench.contract_validator",
        "scripts/build_system_index.py": "workbench.workspace.build_system_index",
        "scripts/list_latest.py": "workbench.workspace.list_latest",
        "scripts/promote_snapshot.py": "workbench.workspace.promote_snapshot",
        "scripts/system_status.py": "workbench.workspace.system_status",
    }
    for rel, module in wrappers.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert module in text
        assert len(text.splitlines()) <= 18


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
