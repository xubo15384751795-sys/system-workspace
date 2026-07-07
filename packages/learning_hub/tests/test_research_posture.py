"""Research-posture engine tests — confidence-aware but action-oriented.

Low confidence limits the claim level, not the research action: the digest must
still surface watch actions and upgrade paths, including for blocked entities.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from system_learning.guards import (
    DEFAULT_REGISTRY_RELPATH,
    build_posture_digest,
    load_registry,
)
from system_learning.guards.posture import _derive_overall
from system_learning.guards.registry import Entity, Posture, Registry

SYSTEM_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = SYSTEM_ROOT / DEFAULT_REGISTRY_RELPATH


@pytest.fixture(scope="module")
def digest():
    registry = load_registry(REGISTRY_PATH)
    return build_posture_digest(registry)


def _entry(digest, name):
    return next(e for e in digest.entries if e.entity == name)


def test_overall_posture_is_active_watch(digest):
    """K_v1 carries ACTIVE_WATCH (top priority) → overall ACTIVE_WATCH."""
    assert digest.overall_posture == "ACTIVE_WATCH"
    assert "K_v1" in digest.overall_reason


def test_prototypes_carry_upgrade_path(digest):
    proto = _entry(digest, "K_neg_SLV_60d")
    assert proto.action_type == "ROBUSTNESS_TEST"
    assert proto.level == "L4_prototype"
    assert proto.upgrade_path  # non-empty: research is promotable, not just blocked
    assert any("walk-forward" in step.lower() for step in proto.upgrade_path)


def test_blocked_entity_still_has_reactivation_path(digest):
    """A contaminated signal is forbidden for use but must still show how to revive it."""
    blocked = _entry(digest, "X_agg_positive_spike")
    assert blocked.action_type == "BLOCKED"
    assert blocked.forbidden
    assert blocked.upgrade_path  # promotion path even for blocked entities


def test_low_confidence_does_not_blank_can_say(digest):
    """Diagnostic-level entities can still say something (graded, not silenced)."""
    k = _entry(digest, "K_v1")
    assert k.level == "L1_diagnostic"
    assert k.can_say.strip()


def test_overall_excludes_blocked_only_registry():
    """If only BLOCKED postures exist, overall falls back to IGNORE, not BLOCKED."""
    entries = build_posture_digest(
        Registry(
            schema_version="t",
            active_claiming_statuses=frozenset(),
            status_enums={},
            entities=(
                Entity(
                    kind="signal",
                    name="x",
                    status="DISABLED_CONTAMINATED",
                    posture=Posture(level="L0_blocked", action_type="BLOCKED"),
                ),
            ),
            posture_priority=("ACTIVE_WATCH", "ROBUSTNESS_TEST", "DATA_REPAIR", "QUIET_WATCH", "IGNORE"),
        )
    )
    assert entries.overall_posture == "IGNORE"


def test_derive_overall_respects_priority():
    from system_learning.guards.posture import PostureEntry

    def mk(action):
        return PostureEntry("e", "signal", "S", "L", action, "", [], [], [])

    entries = [mk("QUIET_WATCH"), mk("ACTIVE_WATCH"), mk("DATA_REPAIR")]
    priority = ("ACTIVE_WATCH", "ROBUSTNESS_TEST", "DATA_REPAIR", "QUIET_WATCH", "IGNORE")
    action, _ = _derive_overall(entries, priority)
    assert action == "ACTIVE_WATCH"
