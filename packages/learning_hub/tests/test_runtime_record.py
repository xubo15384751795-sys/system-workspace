from __future__ import annotations

from pathlib import Path

from system_learning.runtime.record import append_runtime_record, read_runtime_records


def test_append_and_read_runtime_record(tmp_path: Path) -> None:
    path = append_runtime_record(
        tmp_path,
        {
            "subsystem": "workbench",
            "event_type": "test_event",
            "severity": "info",
            "payload": {"ok": True},
        },
    )
    assert path.exists()
    records = read_runtime_records(tmp_path, limit=5)
    assert len(records) == 1
    assert records[0]["event_type"] == "test_event"
    assert records[0]["payload"]["ok"] is True
