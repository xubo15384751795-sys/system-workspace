"""Ledger append and canonicalization tests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from system_learning.ledger.append import (
    append_lifecycle_events,
    append_system_events,
    canonical_events,
    read_lifecycle_ledger,
)
from system_learning.governance.lifecycle_events import lifecycle_event


def _sample_event(event_id: str) -> dict:
    return {
        "event_id": event_id,
        "timestamp": "2026-04-26T00:00:00Z",
        "subsystem": "harvester",
        "event_type": "provider_health_issue",
        "severity": "medium",
        "payload": {"provider": "example"},
        "source_report_path": "/tmp/provider.json",
        "requires_manual_review": True,
    }


def test_append_system_events_dedupes_by_event_id(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledgers"
    event = _sample_event("evt-dup")

    append_system_events(ledger_dir, [event], "run-a")
    append_system_events(ledger_dir, [event], "run-b")

    canonical = canonical_events(ledger_dir)
    assert len(canonical) == 1


def test_lifecycle_ledger_tracks_transitions(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledgers"
    improvement_id = "imp-001"
    append_lifecycle_events(
        ledger_dir,
        [
            lifecycle_event(
                improvement_id=improvement_id,
                transition="approved",
                recorded_by_run="run-1",
                actor="reviewer",
            )
        ],
        "run-1",
    )

    lifecycle = read_lifecycle_ledger(ledger_dir)
    assert len(lifecycle) == 1
    assert lifecycle.loc[0, "improvement_id"] == improvement_id
    assert lifecycle.loc[0, "transition"] == "approved"


def test_canonical_events_sorted_by_timestamp(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledgers"
    append_system_events(ledger_dir, [_sample_event("evt-b")], "run-a")
    append_system_events(
        ledger_dir,
        [
            {
                **_sample_event("evt-a"),
                "timestamp": "2026-04-25T00:00:00Z",
            }
        ],
        "run-b",
    )

    canonical = canonical_events(ledger_dir)
    assert canonical.iloc[0]["event_id"] == "evt-a"
    assert canonical.iloc[1]["event_id"] == "evt-b"
    assert isinstance(canonical, pd.DataFrame)
