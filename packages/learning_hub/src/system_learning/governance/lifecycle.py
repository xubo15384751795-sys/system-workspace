from __future__ import annotations

GOVERNANCE_RULES_VERSION = "lifecycle.v1+issue_rules.v1"

LIFECYCLE_STATES = ["proposed", "approved", "implemented", "verified", "closed", "reopened", "failed"]
ALLOWED_TRANSITIONS = {
    "proposed": {"approved", "failed"},
    "approved": {"implemented", "failed"},
    "implemented": {"verified", "failed"},
    "verified": {"closed", "failed", "reopened"},
    "closed": set(),
    "reopened": {"implemented", "failed"},
    "failed": {"proposed"},
}


def normalize_lifecycle_state(value: str | None) -> str:
    state = str(value or "proposed").strip().lower()
    return state if state in LIFECYCLE_STATES else "proposed"


def can_transition(current: str, target: str) -> bool:
    current = normalize_lifecycle_state(current)
    target = normalize_lifecycle_state(target)
    return target in ALLOWED_TRANSITIONS[current] or current == target
