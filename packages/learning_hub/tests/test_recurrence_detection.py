"""Focused tests for recurrence detection in Learning Hub analyzers."""
from __future__ import annotations

from system_learning.analyzers.recurrence import (
    classify_issue_family,
    event_ledger,
    violation_ledger,
)


def _provider_event(event_id: str, event_type: str) -> dict:
    return {
        "event_id": event_id,
        "timestamp": "2026-04-26T00:00:00Z",
        "subsystem": "harvester",
        "event_type": event_type,
        "severity": "high",
        "payload": {"provider": "example"},
        "source_report_path": "/tmp/provider.json",
        "requires_manual_review": True,
    }


def test_repeated_events_group_into_single_violation_with_recurrence_count() -> None:
    events = [
        _provider_event("evt-1", "provider_health_issue"),
        _provider_event("evt-2", "provider_health_issue"),
        _provider_event("evt-3", "provider_health_issue"),
    ]
    violations = violation_ledger(event_ledger(events))

    assert len(violations) == 1
    assert violations.loc[0, "issue_family"] == "provider_health_issue"
    assert violations.loc[0, "recurrence_count"] == 3


def test_distinct_issue_families_remain_separate() -> None:
    events = [
        _provider_event("evt-1", "provider_health_issue"),
        {
            **_provider_event("evt-2", "architecture_drift"),
            "subsystem": "codebase_cartographer",
            "boundary_type": "architecture_drift",
            "payload": {"message": "oversized file"},
        },
    ]
    violations = violation_ledger(event_ledger(events))

    assert len(violations) == 2
    assert set(violations["issue_family"]) == {"provider_health_issue", "architecture_drift"}


def test_classify_issue_family_uses_event_type_keywords() -> None:
    assert classify_issue_family({"event_type": "ml_constitution_violation"}) == "ml_integrity_violation"
    assert classify_issue_family({"event_type": "benchmark_error"}) == "benchmark_error"
