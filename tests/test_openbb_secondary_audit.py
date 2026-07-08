from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "workbench" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "learning_hub" / "src"))

from system_learning.ingestion.collectors import collect_events
from workbench.openbb_secondary_audit import AuditInputs, run_audit


def test_openbb_secondary_audit_writes_observe_only_learning_event(tmp_path: Path) -> None:
    openbb_run = tmp_path / "Output" / "sandbox" / "openbb" / "runs" / "probe-a"
    deformation_run = tmp_path / "Output" / "deformation_runs" / "run-a"
    audit_dir = tmp_path / "Output" / "workbench" / "openbb_secondary_audits"
    events_dir = tmp_path / "Output" / "system_learning" / "events"
    (openbb_run / "machine").mkdir(parents=True)
    deformation_run.mkdir(parents=True)

    write_json(
        openbb_run / "run_manifest.json",
        {
            "kind": "openbb_probe",
            "schema_version": "sandbox.openbb.run.v1",
            "run_id": "probe-a",
            "status": "success",
            "source_engine": "openbb",
            "route": "/economy/fred_series",
            "provider": "fred",
            "symbol": "VIXCLS",
            "output_paths": {"quality": "machine/quality_report.json"},
        },
    )
    write_json(openbb_run / "machine" / "quality_report.json", {"status": "pass", "series": ["VIXCLS"]})
    write_json(
        deformation_run / "model_run.json",
        {
            "schema_version": "workbench.model_run.v1",
            "run_id": "run-a",
            "model_input_validity": "complete",
        },
    )

    audit = run_audit(
        AuditInputs(
            openbb_run_dir=openbb_run,
            deformation_run_dir=deformation_run,
            output_dir=audit_dir,
            events_dir=events_dir,
        )
    )

    schema = json.loads(
        (ROOT / "packages" / "workbench" / "contracts" / "workbench" / "openbb_secondary_audit.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(audit, schema)
    assert audit["audit_mode"] == "observe_only"
    assert audit["verdict"] == "pass"
    assert audit["compared_series"] == ["VIXCLS"]
    assert audit["non_interference"]["deformation_input_written"] is False
    assert audit["non_interference"]["harvester_release_written"] is False

    audit_files = sorted(audit_dir.glob("*.json"))
    event_files = sorted(events_dir.glob("*.jsonl"))
    assert len(audit_files) == 1
    assert len(event_files) == 1

    event = json.loads(event_files[0].read_text(encoding="utf-8").strip())
    assert event["event_type"] == "openbb_secondary_audit"
    assert event["subsystem"] == "workbench"
    assert event["target_subsystem"] == "deformation"
    assert event["boundary_type"] == "secondary_audit_observe_only"
    assert event["governance_mode"] == "observe_only"
    assert event["payload"]["non_interference"]["allowed_outputs"] == [
        "Output/workbench/openbb_secondary_audits",
        "Output/system_learning/events",
    ]

    collected = collect_events(tmp_path)
    assert any(item["event_id"] == event["event_id"] for item in collected)


def test_openbb_secondary_audit_warns_on_incomplete_deformation_input(tmp_path: Path) -> None:
    openbb_run = tmp_path / "Output" / "sandbox" / "openbb" / "runs" / "probe-b"
    deformation_run = tmp_path / "Output" / "deformation_runs" / "run-b"
    (openbb_run / "machine").mkdir(parents=True)
    deformation_run.mkdir(parents=True)

    write_json(
        openbb_run / "run_manifest.json",
        {
            "kind": "openbb_probe",
            "run_id": "probe-b",
            "status": "success",
            "source_engine": "openbb",
            "symbol": "MOVE",
            "output_paths": {},
        },
    )
    write_json(
        deformation_run / "framework_output.json",
        {
            "schema_version": "workbench.framework_output.v1",
            "run_id": "run-b",
            "model_input_validity": "incomplete",
        },
    )

    audit = run_audit(
        AuditInputs(
            openbb_run_dir=openbb_run,
            deformation_run_dir=deformation_run,
            output_dir=tmp_path / "Output" / "workbench" / "openbb_secondary_audits",
            events_dir=tmp_path / "Output" / "system_learning" / "events",
        )
    )

    assert audit["verdict"] == "warn"
    codes = {finding["code"] for finding in audit["findings"]}
    assert "deformation_input_incomplete" in codes
    assert "openbb_quality_absent" in codes
    event = json.loads(next((tmp_path / "Output" / "system_learning" / "events").glob("*.jsonl")).read_text())
    assert event["governance_mode"] == "manual_review_required"
    assert event["requires_manual_review"] is True


def test_openbb_secondary_audit_rejects_manifest_paths_that_escape_run_dir(tmp_path: Path) -> None:
    openbb_run = tmp_path / "Output" / "sandbox" / "openbb" / "runs" / "probe-c"
    deformation_run = tmp_path / "Output" / "deformation_runs" / "run-c"
    openbb_run.mkdir(parents=True)
    deformation_run.mkdir(parents=True)
    write_json(
        openbb_run / "run_manifest.json",
        {
            "kind": "openbb_probe",
            "run_id": "probe-c",
            "status": "success",
            "source_engine": "openbb",
            "symbol": "VIXCLS",
            "output_paths": {"quality": "../escape.json"},
        },
    )
    write_json(deformation_run / "model_run.json", {"run_id": "run-c"})

    try:
        run_audit(
            AuditInputs(
                openbb_run_dir=openbb_run,
                deformation_run_dir=deformation_run,
                output_dir=tmp_path / "Output" / "workbench" / "openbb_secondary_audits",
                events_dir=tmp_path / "Output" / "system_learning" / "events",
            )
        )
    except ValueError as exc:
        assert "escapes run directory" in str(exc)
    else:
        raise AssertionError("Expected escaping OpenBB output path to be rejected")


def test_openbb_secondary_audit_boundaries_are_static() -> None:
    audit_source = (ROOT / "packages" / "workbench" / "src" / "workbench" / "openbb_secondary_audit.py").read_text(
        encoding="utf-8"
    )
    assert "import openbb" not in audit_source
    assert "from openbb" not in audit_source
    assert "Data/harvester/exports" not in audit_source

    deformation_src = ROOT / "packages" / "framework" / "src"
    offenders: list[str] = []
    for path in deformation_src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import openbb" in text or "from openbb" in text:
            offenders.append(str(path.relative_to(ROOT)))
        if "Output/sandbox/openbb" in text or "OpenBB/" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
