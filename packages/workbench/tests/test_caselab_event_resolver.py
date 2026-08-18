from __future__ import annotations

from nlp.canonical_compat import build_event_resolution_claim
from system_runtime.canonical_ids import validate_claim


def test_event_resolution_claim_is_diagnostic_only() -> None:
    claim = build_event_resolution_claim(
        {
            "status": "resolved",
            "event_text": "A company announced a restructuring",
            "entity": {"id": "company_a", "name": "Company A"},
        }
    )

    validate_claim(claim)
    assert claim["status"] == "WATCH"
    assert claim["evidence_ids"] == []
    assert claim["provenance"]["statement_kind"] == "diagnostic_event_resolution"
    assert claim["provenance"]["claim_ceiling"] == "diagnostic_watch_only"
    assert claim["provenance"]["promotion_allowed"] is False


def test_unresolved_event_claim_is_insufficient_without_evidence() -> None:
    claim = build_event_resolution_claim(
        {"status": "entity_not_found", "query": "unknown_entity"}
    )

    validate_claim(claim)
    assert claim["status"] == "INSUFFICIENT_DATA"
    assert claim["evidence_ids"] == []
