"""Locks the proxy-quality gate behaviour.

The gate (governance/proxy_quality_rules.yaml + scripts/proxy_quality_scorer.py)
decides which wired proxies may vote into a canonical M/D/K/X construct. These
tests pin the invariants that implement the core principle: high-quality proxies
only, no low-quality proxy stuffing into core.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.semantic

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import proxy_quality_scorer as pqs  # noqa: E402

VALID_TIERS = {
    "CORE_ELIGIBLE",
    "CONSTRUCT_SUPPORT",
    "DIAGNOSTIC_ONLY",
    "BACKGROUND_ONLY",
    "REJECTED",
}


@pytest.fixture(scope="module")
def scored() -> dict[str, dict]:
    rules = pqs.load_rules()
    registry = pqs.srv2.PROXY_REGISTRY
    fam = pqs.channel_family_counts(registry)
    rows = [pqs.score_proxy(p, rules, fam.get(p.target_variable, 0)) for p in registry]
    return {r["name"]: r for r in rows}


def test_every_proxy_gets_exactly_one_valid_tier(scored: dict) -> None:
    assert scored, "registry produced no rows"
    for name, row in scored.items():
        assert row["quality_tier"] in VALID_TIERS, f"{name}: {row['quality_tier']}"


def test_quarantined_drift_is_rejected(scored: dict) -> None:
    # T10Y2Y is a curve slope, not anchor mismatch — quarantined, must not vote.
    assert scored["M_curve_inversion"]["quality_tier"] == "REJECTED"


def test_extension_beyond_canonical_is_rejected(scored: dict) -> None:
    # The retired daily X_PRE / X_REALIZED split must never reach a voting tier.
    for name in ("X_PRE_leverage_trace", "X_REALIZED_vix_jump"):
        assert scored[name]["quality_tier"] == "REJECTED"


def test_awaiting_data_is_rejected(scored: dict) -> None:
    name = "M_canonical_NOT_IMPLEMENTED_m3_liquidation_gap"
    assert scored[name]["canonical_status"] == "awaiting_data"
    assert scored[name]["quality_tier"] == "REJECTED"


def test_pi_observable_is_background_only(scored: dict) -> None:
    # H41 facility usage is a Pi_t validation observable, never a channel voter.
    assert scored["Pi_t_observable_primary_credit"]["quality_tier"] == "BACKGROUND_ONLY"


def test_canonical_voting_daily_multifamily_is_core_eligible(scored: dict) -> None:
    # Options-derived K with >=2 families, daily, full mechanism — the kind of
    # proxy the gate is meant to admit.
    row = scored["K_vix_term_structure_twist"]
    assert row["canonical_status"] == "canonical_voting"
    assert row["frequency_fit"] == "full"
    assert row["channel_family_count"] >= 2
    assert row["quality_tier"] == "CORE_ELIGIBLE"


def test_voting_proxy_at_background_frequency_cannot_reach_core(scored: dict) -> None:
    # Quarterly OBS votes but is background-frequency: never CORE_ELIGIBLE.
    row = scored["X_agg_off_balance_sheet_v1"]
    assert row["freq"] == "quarterly"
    assert row["quality_tier"] == "BACKGROUND_ONLY"


def test_empirical_criteria_are_declared_pending_not_fabricated(scored: dict) -> None:
    for row in scored.values():
        assert row["regime_coverage"] == "pending_empirical"
        assert row["discrimination_power"] == "pending_empirical"
        assert row["baseline_increment"] == "pending_empirical"


def test_legacy_proxy_first_drift_is_flagged() -> None:
    # The user's named cases: K=VIX, X=H41, M=T10Y2Y in compute_proxies.py.
    rules = pqs.load_rules()
    findings = pqs.scan_legacy(rules)
    flagged = {(f["channel"], f["series"]) for f in findings}
    assert ("K_PROXY", "FRED:VIXCLS") in flagged
    assert ("X_PROXY", "H41:primary_credit") in flagged
    assert ("M_PROXY", "FRED:T10Y2Y") in flagged
    assert all(f["verdict"] == "REJECTED" for f in findings)


def test_declared_core_conflict_surfaces_oas_credit_in_k(scored: dict) -> None:
    # K's declared-core OAS credit surface is canonically excluded from K
    # (K is NOT a credit spread) — must be flagged as a conflict, not silently
    # admitted.
    row = scored["K_credit_surface_HY_minus_IG"]
    assert row["declared_tier"] == "core"
    assert row["quality_tier"] == "REJECTED"
    assert row["declared_core_conflict"] is True
