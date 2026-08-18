"""Compatibility helpers for exposing NLP candidates on the canonical chain.

NLP event cards are extracted hypotheses, not first-class observations. This
module gives them a stable Claim identity for lineage and replay while keeping
the promotion boundary explicit: no canonical Evidence ID is fabricated from
an unpromoted text quote.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from system_runtime.canonical_ids import build_claim, validate_claim


_CLAIM_STATUS_BY_EVENT_STATUS = {
    "candidate": "WATCH",
    "reviewed": "WATCH",
    "canonical": "WATCH",
    "admitted": "WATCH",
    "rejected": "CONFLICTED",
    "needs_revision": "CONFLICTED",
}


def build_event_card_claim(card: Any, *, legacy_status: str | None = None) -> dict[str, Any]:
    """Build a standalone, diagnostic-only Claim for an event card.

    The source quote remains in the NLP card and candidate ledger. It is not
    treated as an ``evd_`` record until a later evidence writer has a real
    Observation -> Measurement -> Evidence path, so ``evidence_ids`` stays
    empty by design.
    """
    effective_status = str(legacy_status if legacy_status is not None else card.status)
    status = _CLAIM_STATUS_BY_EVENT_STATUS.get(effective_status, "WATCH")
    event_id = str(card.event_id).strip()
    event_name = " ".join(str(card.event_name).split())
    return build_claim(
        claim_text=f"Structural event candidate: {event_name}",
        subject=event_id,
        predicate="structural_event_candidate",
        policy_version="nlp_event_card.v0.2",
        evidence_ids=[],
        status=status,
        confidence=None,
        provenance={
            "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "producer": "workbench.nlp.event_card_writer",
            "legacy_event_id": event_id,
            "legacy_status": effective_status,
            "claim_ceiling": "diagnostic_watch_only",
            "promotion_allowed": False,
            "evidence_boundary": "source_quote_not_canonical_evidence",
        },
    )


def build_event_resolution_claim(result: dict[str, Any]) -> dict[str, Any]:
    """Build a diagnostic Claim for CaseLab event resolution output.

    Event resolution combines entity context, rule-based event parsing, and a
    historical precedent. It is useful for discovery, but it is not a source
    observation or admitted evidence; the claim therefore has no evidence IDs
    and cannot authorize promotion.
    """
    status = str(result.get("status") or "")
    entity = result.get("entity") if isinstance(result.get("entity"), dict) else {}
    entity_id = str(entity.get("id") or result.get("query") or "unknown")
    event_text = " ".join(str(result.get("event_text") or "").split())
    claim_status = "WATCH" if status == "resolved" else "INSUFFICIENT_DATA"
    claim_text = (
        f"Event resolution for {entity_id} is available for bounded diagnostic review."
        if status == "resolved"
        else f"Event resolution could not establish a CaseLab entity context for {entity_id}."
    )
    claim = build_claim(
        claim_text=claim_text,
        subject=entity_id,
        predicate="case_lab_event_resolution",
        policy_version="nlp.caselab.event_resolver.v1",
        evidence_ids=[],
        status=claim_status,
        confidence=None,
        provenance={
            "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "producer": "workbench.nlp.caselab.event_resolver",
            "legacy_status": status,
            "event_text": event_text,
            "statement_kind": "diagnostic_event_resolution",
            "claim_ceiling": "diagnostic_watch_only",
            "promotion_allowed": False,
            "evidence_boundary": "case_context_and_rule_output_not_canonical_evidence",
        },
    )
    validate_claim(claim)
    return claim


def attach_event_card_claim(card: Any) -> dict[str, Any]:
    """Attach and validate the additive canonical Claim on an event card."""
    existing = getattr(card, "canonical_claim", None)
    existing_id = str(getattr(card, "canonical_claim_id", "") or "")
    existing_status = str((existing or {}).get("provenance", {}).get("legacy_status", ""))
    if existing and existing_id == str(existing.get("claim_id", "")) and existing_status == str(card.status):
        validate_claim(existing)
        return existing
    claim = build_event_card_claim(card)
    validate_claim(claim)
    card.canonical_claim_id = claim["claim_id"]
    card.canonical_claim = claim
    return claim


def event_card_payload(card: Any) -> dict[str, Any]:
    """Serialize a card while retaining optional canonical compatibility data."""
    payload = card.model_dump(mode="json")
    claim = getattr(card, "canonical_claim", None)
    if claim:
        payload["canonical_claim_id"] = str(getattr(card, "canonical_claim_id", "") or claim["claim_id"])
        payload["canonical_claim"] = claim
    return payload
