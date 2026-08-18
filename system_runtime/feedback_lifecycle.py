"""Fail-closed lifecycle event contract for feedback samples.

The lifecycle is governance evidence, not a calibration permission.  Transition
IDs are deterministic so a replay or migration cannot silently create a second
identity for the same sample/state transition.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

LIFECYCLE_STATES = frozenset(
    {
        "candidate",
        "eligible",
        "reviewed",
        "accepted",
        "rejected",
        "deferred",
        "calibration_set",
    }
)
LIFECYCLE_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"candidate"}),
    "candidate": frozenset({"eligible", "rejected", "deferred"}),
    "eligible": frozenset({"reviewed", "rejected", "deferred"}),
    "reviewed": frozenset({"accepted", "rejected", "deferred"}),
    "accepted": frozenset({"calibration_set"}),
    "rejected": frozenset(),
    "deferred": frozenset({"eligible", "rejected"}),
    "calibration_set": frozenset(),
}
GOLDEN_ADJUDICATION_REQUIRED_FIELDS = (
    "criteria_version",
    "adjudicator",
    "occurred_at",
    "evidence",
)


def transition_event_id(sample_id: str, from_state: str | None, to_state: str) -> str:
    """Return the stable identity for one sample lifecycle transition."""
    payload = "|".join((str(sample_id), from_state or "", str(to_state)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_transition_event(
    *,
    sample_id: str,
    from_state: str | None,
    to_state: str,
    owner: str,
    occurred_at: str,
    evidence: Iterable[str],
) -> dict[str, Any]:
    """Build one explicit lifecycle event without granting authority."""
    if not str(sample_id).strip():
        raise ValueError("sample_id must not be empty")
    if from_state is not None and from_state not in LIFECYCLE_STATES:
        raise ValueError(f"unknown from_state: {from_state}")
    if to_state not in LIFECYCLE_STATES:
        raise ValueError(f"unknown to_state: {to_state}")
    if not str(owner).strip():
        raise ValueError("owner must not be empty")
    if not str(occurred_at).strip():
        raise ValueError("occurred_at must not be empty")
    evidence_values = sorted({str(item).strip() for item in evidence if str(item).strip()})
    if not evidence_values:
        raise ValueError("lifecycle evidence must not be empty")
    return {
        "event_id": transition_event_id(sample_id, from_state, to_state),
        "from_state": from_state,
        "to_state": to_state,
        "owner": str(owner),
        "occurred_at": str(occurred_at),
        "evidence": evidence_values,
    }


def validate_golden_adjudication(value: Any) -> list[str]:
    """Return violations for the separate, versioned golden-set adjudication."""
    if not isinstance(value, dict):
        return ["not_object"]
    violations: list[str] = []
    for field in GOLDEN_ADJUDICATION_REQUIRED_FIELDS[:3]:
        if not str(value.get(field) or "").strip():
            violations.append(f"missing_{field}")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not any(str(item).strip() for item in evidence):
        violations.append("missing_evidence")
    return violations


def validate_lifecycle_events(
    sample_id: str,
    events: Any,
    *,
    current_state: str | None = None,
) -> list[str]:
    """Return explicit contract violations for a sample's transition events."""
    if not isinstance(events, list) or not events:
        return ["missing_lifecycle_events"]
    violations: list[str] = []
    seen: set[str] = set()
    previous_to_state: str | None = None
    for index, event in enumerate(events):
        prefix = f"lifecycle_events[{index}]"
        if not isinstance(event, dict):
            violations.append(f"{prefix}:not_object")
            continue
        from_state = event.get("from_state")
        to_state = event.get("to_state")
        event_id = str(event.get("event_id") or "")
        expected_id = transition_event_id(str(sample_id), from_state, str(to_state or ""))
        if not event_id or event_id != expected_id:
            violations.append(f"{prefix}:unstable_event_id")
        if event_id in seen:
            violations.append(f"{prefix}:duplicate_event_id")
        seen.add(event_id)
        if from_state is not None and from_state not in LIFECYCLE_STATES:
            violations.append(f"{prefix}:unknown_from_state")
        if to_state not in LIFECYCLE_STATES:
            violations.append(f"{prefix}:unknown_to_state")
        allowed_targets = LIFECYCLE_TRANSITIONS.get(from_state, frozenset())
        if to_state not in allowed_targets:
            violations.append(f"{prefix}:invalid_transition")
        if index == 0 and from_state is not None:
            violations.append(f"{prefix}:first_event_must_start_at_null")
        if index > 0 and from_state != previous_to_state:
            violations.append(f"{prefix}:transition_chain_break")
        if not str(event.get("owner") or "").strip():
            violations.append(f"{prefix}:missing_owner")
        if not str(event.get("occurred_at") or "").strip():
            violations.append(f"{prefix}:missing_occurred_at")
        evidence = event.get("evidence")
        if not isinstance(evidence, list) or not any(str(item).strip() for item in evidence):
            violations.append(f"{prefix}:missing_evidence")
        previous_to_state = str(to_state) if to_state in LIFECYCLE_STATES else previous_to_state
    if current_state is not None and previous_to_state != current_state:
        violations.append("current_state_does_not_match_last_transition")
    return violations


__all__ = [
    "GOLDEN_ADJUDICATION_REQUIRED_FIELDS",
    "LIFECYCLE_STATES",
    "LIFECYCLE_TRANSITIONS",
    "make_transition_event",
    "transition_event_id",
    "validate_golden_adjudication",
    "validate_lifecycle_events",
]
