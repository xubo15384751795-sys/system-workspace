"""Governance lifecycle helpers and policy entry points."""

from system_learning.governance.lifecycle import (
    ALLOWED_TRANSITIONS,
    LIFECYCLE_STATES,
    can_transition,
    normalize_lifecycle_state,
)
from system_learning.ml_integrity import run_pollution_check

__all__ = [
    "ALLOWED_TRANSITIONS",
    "LIFECYCLE_STATES",
    "can_transition",
    "normalize_lifecycle_state",
    "run_pollution_check",
]
