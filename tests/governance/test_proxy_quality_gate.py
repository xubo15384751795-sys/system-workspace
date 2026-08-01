"""Proxy quality gate behaviour, against the live report builder.

Replaces tests/governance/test_proxy_quality_scorer.py, which targeted
scripts/proxy_quality_scorer.py — archived on 2026-06-18 in 7023b75 as one of
eight dead scripts, and not present in scripts/archive/ either. That file's
ten tests had been skipping ever since under the reason "replay.scoring not
available", which pointed at a module that does exist
(packages/framework/src/replay/scoring.py), so the gap read as an environment
problem rather than as missing coverage.

The rules these lock are the operational form of the principle stated in
governance/proxy_quality_rules.yaml: "high-quality proxies only — stop
stuffing low-quality proxies into core." Each expectation below was checked
against the live builder before being written here; none is aspirational.
"""
from __future__ import annotations

import pytest

from scripts.commands.weekly import build_proxy_quality_report as bpq

VALID_TIERS = {
    "CORE_ELIGIBLE",
    "CONSTRUCT_SUPPORT",
    "DIAGNOSTIC_ONLY",
    "BACKGROUND_ONLY",
    "REJECTED",
}

# Criteria the rules file's HONESTY RULE says must never be fabricated: they
# need price/return history the gate does not have.
EMPIRICAL_CRITERIA = ("regime_coverage", "discrimination_power", "baseline_increment")


@pytest.fixture(scope="module")
def rows() -> dict[str, dict]:
    report = bpq.build_report()
    return {r["name"]: r for r in report["proxies"]}


class TestTierAssignment:
    def test_every_proxy_gets_exactly_one_valid_tier(self, rows):
        assert rows, "registry produced no rows"
        for name, row in rows.items():
            assert row["quality_tier"] in VALID_TIERS, f"{name}: {row['quality_tier']}"

    def test_quarantined_drift_is_rejected(self, rows):
        """T10Y2Y is a curve slope, not an anchor mismatch."""
        assert rows["M_curve_inversion"]["quality_tier"] == "REJECTED"

    def test_extension_beyond_canonical_is_rejected(self, rows):
        """The retired daily X_PRE / X_REALIZED split must never vote."""
        for name in ("X_PRE_leverage_trace", "X_REALIZED_vix_jump"):
            assert rows[name]["quality_tier"] == "REJECTED"

    def test_awaiting_data_is_rejected(self, rows):
        row = rows["M_canonical_NOT_IMPLEMENTED_m3_liquidation_gap"]
        assert row["canonical_status"] == "awaiting_data"
        assert row["quality_tier"] == "REJECTED"

    def test_pi_observable_is_background_only(self, rows):
        """H41 facility usage validates Pi_t; it is never a channel voter."""
        assert rows["Pi_t_observable_primary_credit"]["quality_tier"] == "BACKGROUND_ONLY"

    def test_canonical_voting_daily_multifamily_is_core_eligible(self, rows):
        """The shape the gate exists to admit — not everything is rejected."""
        row = rows["K_vix_term_structure_twist"]
        assert row["canonical_status"] == "canonical_voting"
        assert row["frequency_fit"] == "full"
        assert row["channel_family_count"] >= 2
        assert row["quality_tier"] == "CORE_ELIGIBLE"

    def test_background_frequency_proxy_cannot_reach_core(self, rows):
        """A quarterly proxy may vote, but never at core weight."""
        assert rows["X_agg_off_balance_sheet_v1"]["quality_tier"] == "BACKGROUND_ONLY"

    def test_credit_surface_is_excluded_from_k(self, rows):
        """K is not a credit spread. An OAS surface wired into K must be
        rejected as drifted, not silently admitted."""
        row = rows["K_credit_surface_HY_minus_IG"]
        assert row["canonical_status"] == "quarantined_drift"
        assert row["quality_tier"] == "REJECTED"
        assert row["tier_reason"] == "drifted_from_canonical"


class TestHonestyRule:
    def test_empirical_criteria_are_not_fabricated(self, rows):
        """regime_coverage, discrimination_power and baseline_increment need
        price history the gate does not have. They may be absent or declared
        pending — never a fabricated number."""
        for name, row in rows.items():
            for key in EMPIRICAL_CRITERIA:
                if key in row:
                    assert not isinstance(row[key], (int, float)) or isinstance(
                        row[key], bool
                    ), f"{name}.{key} carries a fabricated numeric score: {row[key]!r}"

    def test_rejected_proxies_score_zero(self, rows):
        """A rejected proxy must not carry residual weight."""
        for name, row in rows.items():
            if row["quality_tier"] == "REJECTED":
                assert row["overall_score"] == 0.0, f"{name}: {row['overall_score']}"


class TestGateShape:
    def test_summary_counts_match_rows(self, rows):
        report = bpq.build_report()
        summary = report["summary"]
        assert summary["total"] == len(report["proxies"])
        assert summary["rejected"] == sum(
            1 for r in rows.values() if r["quality_tier"] == "REJECTED"
        )

    def test_gate_actually_rejects(self, rows):
        """A gate that admits everything is not a gate. Guards against the
        tier logic silently degrading to a pass-through."""
        rejected = sum(1 for r in rows.values() if r["quality_tier"] == "REJECTED")
        core = sum(1 for r in rows.values() if r["quality_tier"] == "CORE_ELIGIBLE")
        assert rejected > 0, "no proxy rejected — gate is not discriminating"
        assert core > 0, "no proxy admitted — gate rejects everything"
        assert core < len(rows), "every proxy is core-eligible"
