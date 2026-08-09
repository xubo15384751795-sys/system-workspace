"""Learning Hub runtime append path + collector bridge."""
from __future__ import annotations

import json
from pathlib import Path

from system_learning.ingestion.collectors import event_file_paths
from system_learning.runtime.record import append_runtime_record, read_runtime_records


def test_append_runtime_record_writes_daily_file(tmp_path: Path) -> None:
    path = append_runtime_record(
        tmp_path,
        {
            "subsystem": "daily_pipeline",
            "event_type": "pipeline_run",
            "severity": "info",
            "source_tool": "unit_test",
            "run_id": "run_test",
        },
    )
    assert path.name.startswith("records_")
    assert path.exists()
    records = read_runtime_records(tmp_path, limit=5)
    assert records
    assert records[-1]["event_type"] == "pipeline_run"


def test_collectors_include_operator_runtime_events(tmp_path: Path) -> None:
    runtime = tmp_path / "Output" / "runtime_events"
    runtime.mkdir(parents=True)
    target = runtime / "2026-08-10.jsonl"
    target.write_text(
        json.dumps(
            {
                "schema_version": "system.event_envelope.v1",
                "event_id": "e1",
                "event_type": "daily_run_completed",
                "payload_schema": "run_event.v1",
                "occurred_at": "2026-08-10T00:00:00Z",
                "producer": "daily_run",
                "run_id": "r1",
                "payload": {"status": "success"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    paths = event_file_paths(tmp_path)
    assert target in paths


def test_record_daily_run_event_also_appends_hub_runtime(tmp_path, monkeypatch) -> None:
    from scripts import record_daily_run_event as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "EVENTS_DIR", tmp_path / "Output" / "system_learning" / "events")
    monkeypatch.setattr(mod, "HUB_EVENTS_DIR", tmp_path / "Output" / "runtime_events")
    monkeypatch.setattr(mod, "TRADE_DECISION_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(mod, "EVIDENCE_GRADE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(mod, "STATUS_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(mod, "PROMOTION_GATE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(mod, "_get_git_sha", lambda: "deadbeef")
    monkeypatch.setattr(mod, "_get_submodule_pins", lambda: {})

    event = mod.build_run_event(run_id="run_bridge_test")
    out = mod.record_event(event, force=True)
    assert out is not None
    hub_runtime = tmp_path / "Output" / "system_learning" / "runtime"
    files = list(hub_runtime.glob("records_*.jsonl"))
    assert files, "expected append_runtime_record dual-write"
    body = files[0].read_text(encoding="utf-8")
    assert "pipeline_run" in body
