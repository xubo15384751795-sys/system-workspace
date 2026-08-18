"""Contract tests for typed operator event identity and routing."""
from __future__ import annotations

from system_runtime.operator_events import build_operator_events


def test_provider_publish_and_authority_events_share_run_lineage() -> None:
    events = build_operator_events(
        run_id="run-1",
        release_id="release-1",
        generation_id="run-1",
        provider_check={
            "status": "FAIL",
            "reason_code": "ALL_PROVIDERS_FAILED",
            "provider_status": "all_failed",
        },
        publish_integrity_verdict="BLOCK",
        diagnostic_publish_verdict="BLOCK",
        decision_authority_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
    )

    assert {event["event_type"] for event in events} == {
        "provider_all_failed",
        "publish_verdict",
        "authority_denial",
    }
    for event in events:
        assert event["schema_version"] == "system.operator_event.v1"
        assert event["run_id"] == "run-1"
        assert event["release_id"] == "release-1"
        assert event["generation_id"] == "run-1"
        assert event["event_id"].startswith(event["event_type"] + ":")


def test_operator_event_ids_are_stable_for_same_verdict() -> None:
    kwargs = {
        "run_id": "run-1",
        "release_id": "release-1",
        "generation_id": "run-1",
        "publish_integrity_verdict": "BLOCK",
        "diagnostic_publish_verdict": "BLOCK",
        "decision_authority_verdict": "BLOCK",
        "publish_status": "NOT_PUBLISHED",
        "provider_check": {
            "status": "FAIL",
            "reason_code": "ALL_PROVIDERS_FAILED",
        },
    }
    first = build_operator_events(**kwargs)
    second = build_operator_events(**kwargs)
    assert first == second
    assert first and len({event["event_id"] for event in first}) == len(first)


def test_diagnostic_only_authority_emits_denial_but_not_publish_failure() -> None:
    events = build_operator_events(
        run_id="run-diagnostic",
        release_id="release-1",
        generation_id="run-diagnostic",
        publish_integrity_verdict="PASS",
        diagnostic_publish_verdict="PASS",
        decision_authority_verdict="DIAGNOSTIC_ONLY",
        publish_status="COMMITTED",
    )
    assert [event["event_type"] for event in events] == ["authority_denial"]
    assert events[0]["severity"] == "warning"


def test_canonical_lineage_is_additive_reader_context() -> None:
    lineage = {
        "schema_version": "system.canonical_lineage_reader.v1",
        "authority": "shadow_only",
        "promotion_allowed": False,
        "status": "MATCH",
        "entry_count": 1,
        "entries": [],
    }
    events = build_operator_events(
        run_id="run-1",
        release_id="release-1",
        generation_id="run-1",
        publish_integrity_verdict="BLOCK",
        diagnostic_publish_verdict="BLOCK",
        decision_authority_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        canonical_lineage=lineage,
    )

    assert events
    assert all(event["canonical_lineage"] == lineage for event in events)
    assert all(event["event_type"] in {"publish_verdict", "authority_denial"} for event in events)
