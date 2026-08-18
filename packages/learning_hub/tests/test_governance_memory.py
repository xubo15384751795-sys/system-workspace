from __future__ import annotations

from pathlib import Path

import pandas as pd

from system_learning.analyzers.derive import build_ledgers
from system_learning.analyzers.edges import governance_edges
from system_learning.governance.improvement_contract import improvement_queue_contract_violations
from system_learning.governance.lifecycle_events import derive_lifecycle_states, lifecycle_event
from system_learning.ledger.append import (
    append_lifecycle_events,
    append_system_events,
    canonical_events,
    read_lifecycle_ledger,
)
from system_learning.ledger.store import write_derived_ledgers


def test_append_only_event_log_deduplicates_by_event_id(tmp_path: Path) -> None:
    event = {
        "event_id": "evt-1",
        "timestamp": "2026-05-01T00:00:00Z",
        "subsystem": "harvester",
        "event_type": "provider_health_issue",
        "severity": "medium",
        "payload": {},
        "source_report_path": "",
        "requires_manual_review": False,
    }
    ledger_dir = tmp_path / "ledgers"
    append_system_events(ledger_dir, [event], "run-a")
    append_system_events(ledger_dir, [event], "run-b")

    log = pd.read_parquet(ledger_dir / "system_event_log.parquet")
    assert len(log) == 1
    canonical = canonical_events(ledger_dir)
    assert len(canonical) == 1


def test_improvement_queue_requires_owner_deadline_evidence_and_explicit_decision() -> None:
    incomplete = pd.DataFrame(
        [
            {
                "improvement_id": "imp-incomplete",
                "owner": "",
                "evidence_paths": "[]",
                "evidence_event_ids": "[]",
                "decision": "approved",
            }
        ]
    )
    kinds = {
        item["kind"] for item in improvement_queue_contract_violations(incomplete)
    }
    assert kinds == {"missing_owner", "missing_deadline", "missing_evidence", "invalid_decision"}

    complete = incomplete.assign(
        owner="governance-reviewer",
        deadline="2026-08-19",
        evidence_paths='["Output/runs/run-1/manifest.json"]',
        decision="accepted",
    )
    assert improvement_queue_contract_violations(complete) == []

    authority_attempt = complete.assign(authority_mode="authoritative")
    assert {
        item["kind"] for item in improvement_queue_contract_violations(authority_attempt)
    } == {"authority_grant_attempt"}


def test_lifecycle_state_derived_from_events_not_mutable_queue(tmp_path: Path) -> None:
    improvement_id = "imp-test-001"
    ledger_dir = tmp_path / "ledgers"
    lifecycle_events = [
        lifecycle_event(
            improvement_id=improvement_id,
            transition="proposed",
            recorded_by_run="run-1",
        ),
        lifecycle_event(
            improvement_id=improvement_id,
            transition="approved",
            recorded_by_run="run-2",
            actor="reviewer",
        ),
    ]
    append_lifecycle_events(ledger_dir, lifecycle_events, "run-2")
    states = derive_lifecycle_states(read_lifecycle_ledger(ledger_dir))
    assert states[improvement_id]["lifecycle_state"] == "approved"
    assert states[improvement_id]["owner"] == "reviewer"


def test_governance_edges_sparse_propagation() -> None:
    violations = pd.DataFrame(
        [
            {
                "violation_id": "v1",
                "issue_family": "architecture_drift",
                "subsystem": "codebase_cartographer",
                "event_type": "architecture_drift",
                "severity": "medium",
                "recurrence_count": 2,
                "governance_mode": "manual_review_required",
                "target_subsystem": "",
                "boundary_type": "",
                "first_seen": "",
                "last_seen": "",
                "event_ids": "[]",
                "source_report_paths": "[]",
                "requires_manual_review": True,
            },
            {
                "violation_id": "v2",
                "issue_family": "ml_integrity_violation",
                "subsystem": "ml_integrity",
                "event_type": "ml_constitution_violation",
                "severity": "critical",
                "recurrence_count": 1,
                "governance_mode": "blocker",
                "target_subsystem": "",
                "boundary_type": "",
                "first_seen": "",
                "last_seen": "",
                "event_ids": "[]",
                "source_report_paths": "[]",
                "requires_manual_review": True,
            },
        ]
    )
    edges = governance_edges(violations)
    assert not edges.empty
    assert set(edges["edge_type"]) <= {
        "structural_to_ml_integrity",
        "structural_to_validation",
        "boundary_to_drift",
        "ml_to_validation",
        "upstream_to_validation",
    }


def test_derived_pipeline_includes_edges_and_pressure(tmp_path: Path) -> None:
    events = [
        {
            "event_id": "evt-arch",
            "timestamp": "2026-05-01T00:00:00Z",
            "subsystem": "codebase_cartographer",
            "event_type": "architecture_drift",
            "severity": "high",
            "boundary_type": "architecture_drift",
            "payload": {},
            "source_report_path": "/tmp/a.md",
            "requires_manual_review": True,
        },
        {
            "event_id": "evt-ml",
            "timestamp": "2026-05-02T00:00:00Z",
            "subsystem": "ml_integrity",
            "event_type": "ml_constitution_violation",
            "severity": "critical",
            "payload": {},
            "source_report_path": "/tmp/b.json",
            "requires_manual_review": True,
        },
    ]
    ledgers = build_ledgers(events)
    assert "event_edges" in ledgers
    assert not ledgers["event_edges"].empty
    assert "governance_pressure_score" in ledgers["improvement_queue"].columns

    write_derived_ledgers(tmp_path / "ledgers", ledgers, "run-test")
    summary_path = tmp_path / "ledgers" / "improvement_queue.parquet"
    assert summary_path.exists()
