from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from system_learning.analyzers.derive import build_derived_ledgers, build_ledgers
from system_learning.governance.lifecycle_events import lifecycle_event
from system_learning.ledger.append import (
    append_lifecycle_events,
    append_system_events,
    canonical_events,
    read_lifecycle_ledger,
)
from system_learning.ingestion.collectors import collect_events
from system_learning.ledger.query import ledger_summary
from system_learning.ledger.store import read_existing_improvement_queue, write_ledgers
from system_learning.reports.writer import write_reports
from system_learning.schema import normalize_event


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_collects_standardized_peer_events(tmp_path: Path) -> None:
    write_jsonl(
        tmp_path / "Output" / "deformation_runs" / "run-a" / "system_events.jsonl",
        [
            {
                "event_id": "evt-1",
                "timestamp": "2026-04-26T00:00:00Z",
                "subsystem": "deformation",
                "event_type": "benchmark_error",
                "severity": "high",
                "run_id": "run-a",
                "payload": {"metric": "rmse"},
                "recommended_action": "Review benchmark calibration.",
                "requires_manual_review": True,
            }
        ],
    )
    write_jsonl(
        tmp_path / "Data" / "harvester" / "exports" / "release-a" / "system_events.jsonl",
        [
            {
                "event_id": "evt-2",
                "timestamp": "2026-04-26T01:00:00Z",
                "subsystem": "harvester",
                "event_type": "provider_health_issue",
                "severity": "medium",
                "bundle_id": "release-a",
                "payload": {"provider": "example"},
            }
        ],
    )

    events = collect_events(tmp_path)

    assert {event["event_id"] for event in events} == {"evt-1", "evt-2"}
    assert all("payload" in event for event in events)


def test_ledgers_reports_and_state_preservation(tmp_path: Path) -> None:
    events = [
        {
            "event_id": "evt-1",
            "timestamp": "2026-04-26T00:00:00Z",
            "subsystem": "deformation",
            "event_type": "boundary_violation",
            "severity": "critical",
            "run_id": "run-a",
            "bundle_id": "",
            "payload": {"target": "proxy definitions"},
            "recommended_action": "",
            "source_report_path": "/tmp/report.md",
            "requires_manual_review": True,
        }
    ]
    ledger_dir = tmp_path / "ledgers"
    append_system_events(ledger_dir, events, "seed-run")
    ledgers = build_derived_ledgers(canonical_events(ledger_dir), read_lifecycle_ledger(ledger_dir))
    write_ledgers(ledger_dir, ledgers, "seed-run")

    queue = pd.read_parquet(ledger_dir / "improvement_queue.parquet")
    assert len(queue) == 1
    assert "verification_criteria" in queue.columns
    assert queue.loc[0, "approval_status"] == "pending"
    assert queue.loc[0, "systemic_risk_tag"] == "layer_collapse"
    improvement_id = str(queue.loc[0, "improvement_id"])
    append_lifecycle_events(
        ledger_dir,
        [
            lifecycle_event(
                improvement_id=improvement_id,
                transition="approved",
                recorded_by_run="test-run",
                actor="governance-reviewer",
            )
        ],
        "test-run",
    )

    event_df = canonical_events(ledger_dir)
    lifecycle_df = read_lifecycle_ledger(ledger_dir)
    rebuilt = build_derived_ledgers(event_df, lifecycle_df, metadata_cache=read_existing_improvement_queue(ledger_dir))
    assert rebuilt["improvement_queue"].loc[0, "lifecycle_state"] == "approved"
    assert rebuilt["improvement_queue"].loc[0, "owner"] == "governance-reviewer"

    report_paths = write_reports(tmp_path / "reports", rebuilt)
    assert report_paths["recurrence_report"].exists()
    assert report_paths["summary"].exists()
    assert "boundary_violation" in report_paths["recurrence_report"].read_text(encoding="utf-8")
    summary = json.loads(report_paths["summary"].read_text(encoding="utf-8"))
    assert summary["overall"]["active_improvement_items"] == 1


def test_payload_field_names_do_not_force_boundary_classification() -> None:
    events = [
        {
            "event_id": "evt-architecture",
            "timestamp": "2026-04-26T00:00:00Z",
            "subsystem": "codebase_cartographer",
            "event_type": "architecture_drift",
            "severity": "medium",
            "boundary_type": "architecture_drift",
            "payload": {"boundary_type": "architecture_drift", "message": "File exceeds 800 lines."},
            "source_report_path": "/tmp/architecture_drift.md",
            "requires_manual_review": True,
        }
    ]

    ledgers = build_ledgers(events)
    violations = ledgers["violation_ledger"]

    assert violations.loc[0, "issue_family"] == "architecture_drift"


def test_normalize_event_uses_typed_schema_defaults(tmp_path: Path) -> None:
    source = tmp_path / "reports" / "learning" / "note.md"
    source.parent.mkdir(parents=True)
    source.write_text("learning", encoding="utf-8")

    event = normalize_event(
        {
            "event_type": "provider_health_issue",
            "severity": "warning",
            "confidence": "certain",
            "payload": "provider timeout",
            "unexpected_field": "preserved",
        },
        source,
    )

    assert event["event_id"]
    assert event["severity"] == "medium"
    assert event["confidence"] == "medium"
    assert event["context_type"] == "documentation"
    assert event["payload"]["value"] == "provider timeout"
    assert event["payload"]["source_extra_fields"] == {"unexpected_field": "preserved"}


def test_distinct_event_types_get_distinct_improvement_ids() -> None:
    base_event = {
        "timestamp": "2026-04-26T00:00:00Z",
        "subsystem": "codebase_cartographer",
        "severity": "medium",
        "boundary_type": "architecture_drift",
        "payload": {"message": "architecture drift"},
        "source_report_path": "/tmp/architecture_drift.md",
        "requires_manual_review": True,
    }
    events = [
        {**base_event, "event_id": "evt-drift", "event_type": "architecture_drift"},
        {**base_event, "event_id": "evt-large", "event_type": "oversized_file"},
    ]

    queue = build_ledgers(events)["improvement_queue"]

    assert len(set(queue["improvement_id"])) == 2


def test_collects_ml_integrity_json_events(tmp_path: Path) -> None:
    event_path = (
        tmp_path
        / "Output"
        / "system_learning"
        / "events"
        / "ml_constitution_CONST-01_20260426T120000Z.json"
    )
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text(
        json.dumps(
            {
                "event_type": "ml_constitution_violation",
                "subsystem": "ml_integrity",
                "severity": "red",
                "governance_mode": "blocker",
                "timestamp": "2026-04-26T12:00:00Z",
                "payload": {"rule_id": "CONST-01"},
                "recommended_action": "HALT signal promotion and investigate.",
                "requires_manual_review": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    events = collect_events(tmp_path)

    assert len(events) == 1
    assert events[0]["severity"] == "critical"
    assert events[0]["subsystem"] == "ml_integrity"
    ledgers = build_ledgers(events)
    assert ledgers["violation_ledger"].loc[0, "issue_family"] == "ml_integrity_violation"


def test_duckdb_ledger_summary_reads_parquet_ledgers(tmp_path: Path) -> None:
    events = [
        {
            "event_id": "evt-1",
            "timestamp": "2026-04-26T00:00:00Z",
            "subsystem": "harvester",
            "event_type": "provider_health_issue",
            "severity": "high",
            "payload": {"provider": "example"},
            "source_report_path": "/tmp/provider.json",
            "requires_manual_review": True,
        }
    ]
    ledgers = build_ledgers(events)
    ledger_dir = tmp_path / "ledgers"
    write_ledgers(ledger_dir, ledgers)

    summary = ledger_summary(ledger_dir)

    assert summary["events"] == 1
    assert summary["violations"] == 1
    assert summary["improvement_items"] == 1
    assert summary["subsystems"][0]["subsystem"] == "harvester"
    assert summary["top_issues"][0]["issue_family"] == "provider_health_issue"
