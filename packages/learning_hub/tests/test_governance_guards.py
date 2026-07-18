"""Governance guard tests — enforce that contaminated/frozen/missing-artifact
entities cannot leak back onto the live daily surface."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from system_learning.guards import (
    DEFAULT_REGISTRY_RELPATH,
    load_registry,
    run_governance_audit,
)
from system_learning.guards.audit import (
    guard_artifact_reality,
    guard_daily_readout_contract,
    guard_forbidden_reference,
    guard_registry_integrity,
)
from system_learning.guards.registry import Entity, Registry

SYSTEM_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = SYSTEM_ROOT / DEFAULT_REGISTRY_RELPATH


@pytest.fixture(scope="module")
def registry() -> Registry:
    assert REGISTRY_PATH.exists(), f"seeded registry missing: {REGISTRY_PATH}"
    return load_registry(REGISTRY_PATH)


def _names(findings) -> set[str]:
    return {f.entity for f in findings}


def test_x_agg_positive_spike_blocked_as_daily_trigger(registry: Registry):
    """A daily note citing X_agg_positive_spike must be blocked."""
    corpus = "Today X_agg_positive_spike fired — strong signal, consider SPY entry."
    findings = guard_forbidden_reference(registry, corpus)
    assert "X_agg_positive_spike" in _names(findings)
    assert all(f.severity == "block" for f in findings)


def test_x_agg_spike_strategy_not_active(registry: Registry):
    """The frozen X_agg_spike_SPY_60d strategy must not be cited as active."""
    corpus = "Backtest pipeline reactivated X_agg_spike_SPY_60d as a live strategy."
    findings = guard_forbidden_reference(registry, corpus)
    assert "X_agg_spike_SPY_60d" in _names(findings)


def test_x_agg_channel_reference_is_not_blocked(registry: Registry):
    """The live X_agg channel name alone must NOT trip the guard (no false positive)."""
    corpus = "Channels live: M, D, K, X_agg. Dominant: K."
    findings = guard_forbidden_reference(registry, corpus)
    assert findings == []


def test_clean_daily_surface_passes(registry: Registry):
    corpus = "Structural framework ACTIVE_FULL. Dominant: K. Continue observation."
    findings = guard_forbidden_reference(registry, corpus)
    assert findings == []


def test_missing_artifact_for_active_module_is_caught(tmp_path: Path):
    """A module that claims an active status but whose artifact is missing → REALITY_MISMATCH."""
    reg = Registry(
        schema_version="test",
        active_claiming_statuses=frozenset({"ACTIVE_IN_DAILY"}),
        status_enums={"module": frozenset({"ACTIVE_IN_DAILY"})},
        entities=(
            Entity(
                kind="module",
                name="phantom_module",
                status="ACTIVE_IN_DAILY",
                expect_artifact="Output/does_not_exist/phantom.json",
            ),
        ),
    )
    findings = guard_artifact_reality(reg, tmp_path)
    assert "phantom_module" in _names(findings)
    assert all(f.severity == "block" for f in findings)
    assert "REALITY_MISMATCH" in findings[0].detail


def test_honest_missing_artifact_module_not_flagged(registry: Registry):
    """K_v2 is honestly labeled MISSING_ARTIFACT (not active) → no reality mismatch."""
    findings = guard_artifact_reality(registry, SYSTEM_ROOT)
    assert "k_v2" not in _names(findings)


def test_registry_integrity_flags_unknown_status():
    reg = Registry(
        schema_version="test",
        active_claiming_statuses=frozenset(),
        status_enums={"signal": frozenset({"CANONICAL"})},
        entities=(Entity(kind="signal", name="weird", status="NONSENSE"),),
    )
    findings = guard_registry_integrity(reg)
    assert "weird" in _names(findings)


def test_seeded_registry_is_internally_consistent(registry: Registry):
    """Every status in the seeded registry must be a known enum value."""
    findings = guard_registry_integrity(registry)
    assert findings == [], f"registry integrity findings: {findings}"


def test_full_audit_on_clean_corpus_passes():
    report = run_governance_audit(
        SYSTEM_ROOT,
        registry_path=REGISTRY_PATH,
        daily_corpus="Dominant: K. Continue observation. No contaminated signals cited.",
        now=datetime.now(UTC),
    )
    assert report.ok, f"unexpected block findings: {[f for f in report.findings if f.severity == 'block']}"
    assert set(report.passed_guards) >= {"forbidden_reference", "registry_integrity"}


def test_governance_region_is_stripped_from_scan():
    """Registry-derived governance text (blocked entities + reactivation) is skipped."""
    from system_learning.guards.audit import strip_governance_regions

    text = (
        "free prose before\n"
        "<!-- GOVERNANCE_POSTURE_START -->\n"
        "X_agg_positive_spike is forbidden for: daily trigger\n"
        "<!-- GOVERNANCE_POSTURE_END -->\n"
        "free prose after"
    )
    stripped = strip_governance_regions(text)
    assert "X_agg_positive_spike" not in stripped
    assert "free prose before" in stripped and "free prose after" in stripped


def test_blocked_term_outside_governance_region_still_flagged(registry: Registry):
    """A contaminated signal cited in FREE prose (outside markers) must still block."""
    from system_learning.guards.audit import strip_governance_regions

    text = (
        "Daily note: X_agg_positive_spike is our strongest current strategy.\n"
        "<!-- GOVERNANCE_POSTURE_START -->\ngovernance docs\n<!-- GOVERNANCE_POSTURE_END -->"
    )
    findings = guard_forbidden_reference(registry, strip_governance_regions(text))
    assert "X_agg_positive_spike" in _names(findings)


def test_daily_readout_contract_blocks_cofire_as_primary_state():
    findings = guard_daily_readout_contract("cofire_count is the primary executive state today.")
    assert "cofire_count" in _names(findings)
    assert all(f.severity == "block" for f in findings)


def test_daily_readout_contract_blocks_x_agg_trigger_reactivation():
    findings = guard_daily_readout_contract("X_agg daily trigger restored and active.")
    assert "X_agg" in _names(findings)


def test_daily_readout_contract_blocks_kx_removal_from_framework():
    findings = guard_daily_readout_contract("K/X removed from canonical framework and SigmaVector.")
    assert "K/X" in _names(findings)


def test_daily_readout_contract_allows_governance_negations():
    corpus = (
        "Do not use cofire_count as primary executive state.\n"
        "X_agg daily trigger remains disabled.\n"
        "K/X are not removed from canonical framework."
    )
    assert guard_daily_readout_contract(corpus) == []


def test_full_audit_blocks_contaminated_corpus():
    report = run_governance_audit(
        SYSTEM_ROOT,
        registry_path=REGISTRY_PATH,
        daily_corpus="Daily note: X_agg_positive_spike is our strongest current strategy.",
        now=datetime.now(UTC),
    )
    assert not report.ok
    assert "forbidden_reference" in report.failed_guards
    assert any(f.entity == "X_agg_positive_spike" for f in report.blocked_references())
