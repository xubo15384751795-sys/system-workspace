from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from system_learning.cartography.report import write_cartography_outputs
from system_learning.cartography.scanner import scan_project


def test_codebase_cartographer_outputs_reports_and_events(tmp_path: Path) -> None:
    scan_root = tmp_path / "scan"
    project_root = tmp_path / "hub"
    ui_file = scan_root / "Structural Deformation Research System" / "src" / "ui" / "app.py"
    ui_file.parent.mkdir(parents=True, exist_ok=True)
    ui_file.write_text("import harvester\n\nclass Screen:\n    pass\n", encoding="utf-8")

    scans = scan_project(scan_root)
    outputs = write_cartography_outputs(project_root, scan_root, scans)

    assert outputs["codebase_structure_report"].exists()
    assert outputs["module_metrics"].exists()
    assert outputs["dependency_edges"].exists()
    assert outputs["layer_violations"].exists()
    assert outputs["complexity_hotspots"].exists()
    assert outputs["architecture_drift"].exists()
    assert outputs["system_events"].exists()
    assert outputs["history"].exists()

    violations = json.loads(outputs["layer_violations"].read_text(encoding="utf-8"))
    assert any(item["violation_type"] == "forbidden_dependency" for item in violations)
    events = [json.loads(line) for line in outputs["system_events"].read_text(encoding="utf-8").splitlines()]
    assert any(event["event_type"] == "forbidden_dependency" for event in events)
    assert all(event["source_tool"] == "codebase_cartographer" for event in events)
    assert all("governance_mode" in event for event in events)

    history = pd.read_parquet(outputs["history"])
    assert not history.empty


def test_ui_scope_rules_apply_inside_deformation_project(tmp_path: Path) -> None:
    scan_root = tmp_path / "scan"
    project_root = tmp_path / "hub"
    ui_file = scan_root / "Structural Deformation Research System" / "src" / "ui" / "view.py"
    ui_file.parent.mkdir(parents=True, exist_ok=True)
    ui_file.write_text("from src.proxies import sigma_proxy\n", encoding="utf-8")

    outputs = write_cartography_outputs(project_root, scan_root, scan_project(scan_root))
    violations = json.loads(outputs["layer_violations"].read_text(encoding="utf-8"))

    assert any(item["details"].get("rule") == "ui_forbidden_subsystem_import" for item in violations)


def test_test_context_path_references_are_observations(tmp_path: Path) -> None:
    scan_root = tmp_path / "scan"
    project_root = tmp_path / "hub"
    test_file = scan_root / "Structural Deformation Research System" / "tests" / "test_boundary.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text('PATH = "Data/harvester/raw/example.json"\n', encoding="utf-8")

    outputs = write_cartography_outputs(project_root, scan_root, scan_project(scan_root))
    events = [json.loads(line) for line in outputs["system_events"].read_text(encoding="utf-8").splitlines()]

    assert events[0]["context_type"] == "test_code"
    assert events[0]["confidence"] == "low"
    assert events[0]["governance_mode"] == "observe_only"
    assert events[0]["requires_manual_review"] is False
