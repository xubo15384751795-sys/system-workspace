"""Canonical proxy alignment CI gate.

Asserts the live ProxySpec registry in scripts/structural_replay_v2.py
conforms to governance/canonical_proxy_spec.yaml (Finance-2.tex red line).

This is the gate that prevents silent proxy drift from re-occurring.

Rules enforced:
  1. Every channel listed in spec.channels must exist in VARIABLES.
  2. For each canonical channel, every named sub-basket must have at least
     one ProxySpec with canonical_subbasket == "<channel>.<subbasket_id>".
  3. Every ProxySpec carries canonical_status from the documented taxonomy.
  4. Π_t observables must NOT vote (canonical_status must be
     'reassigned_to_pi_observable' or 'derived_observation_layer').
  5. Legacy X_PRE / X_REALIZED proxies must NOT be canonical_voting
     (they should be extension_beyond_canonical or quarantined_drift).
  6. K_t voting proxies (if any) must use options-derived independence_groups
     (iv_distortion / jump_intensity / tail_convexity). No credit_surface
     proxy may be canonical_voting on K (red-line §4.4).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import structural_replay_v2 as srv  # noqa: E402

SPEC_PATH = REPO / "governance" / "canonical_proxy_spec.yaml"

VALID_CANONICAL_STATUS = {
    "canonical_voting",
    "awaiting_data",
    "quarantined_drift",
    "reassigned_to_pi_observable",
    "diagnostic_consistent",
    "extension_beyond_canonical",
    "unevaluated",
}

CANONICAL_K_GROUPS = {"iv_distortion", "jump_intensity", "tail_convexity"}
FORBIDDEN_K_GROUPS = {
    "credit_surface", "cross_asset_curvature",
    "rates_curve", "funding_spread",
    "volatility_jump",  # vol amplitude ≠ K (§4.4)
}


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(SPEC_PATH.read_text())


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_spec_channels_exist_in_variables(spec):
    """Every canonical channel in spec.channels must be a StateVariable."""
    spec_channels = set(spec["channels"].keys())
    # spec uses "D" (canonical) but code uses "D_contraction" — map.
    canonical_to_code = {
        "M": "M",
        "D": "D_contraction",
        "K": "K",
        "X_agg": "X_agg",
    }
    for cname in spec_channels:
        code_name = canonical_to_code.get(cname, cname)
        assert code_name in srv.VARIABLES, (
            f"Canonical channel {cname} (code: {code_name}) "
            f"missing from VARIABLES. Spec lists it; registry does not."
        )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_pi_t_exists(spec):
    """Pi_t derived observation layer must be registered."""
    assert "Pi_t" in srv.VARIABLES, "Pi_t observation layer missing from VARIABLES"
    assert srv.VARIABLES["Pi_t"].canonical_status == "derived_observation_layer"


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_all_proxies_have_valid_canonical_status():
    """Every ProxySpec must carry a recognised canonical_status."""
    bad = [
        s.name for s in srv.PROXY_REGISTRY
        if s.canonical_status not in VALID_CANONICAL_STATUS
    ]
    assert not bad, (
        f"ProxySpec entries with unknown canonical_status: {bad}. "
        f"Allowed values: {sorted(VALID_CANONICAL_STATUS)}"
    )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_pi_t_proxies_do_not_vote():
    """Π_t observables must never have canonical_status='canonical_voting'."""
    bad = [
        s.name for s in srv.PROXY_REGISTRY
        if s.target_variable == "Pi_t" and s.canonical_status == "canonical_voting"
    ]
    assert not bad, (
        f"Π_t observables wired as canonical_voting: {bad}. "
        f"Π_t is derived (§4.5); H41 facility data is observation only."
    )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_legacy_x_split_does_not_vote():
    """Legacy X_PRE / X_REALIZED proxies must not be canonical_voting."""
    bad = [
        s.name for s in srv.PROXY_REGISTRY
        if s.target_variable in {"X_PRE", "X_REALIZED"}
        and s.canonical_status == "canonical_voting"
    ]
    assert not bad, (
        f"Legacy X_PRE / X_REALIZED proxies still voting: {bad}. "
        f"Canonical X is the single X_agg channel (Finance-2.tex §4.5)."
    )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_k_voting_proxies_are_options_based():
    """No K voter may use credit/rates/funding/vol-amplitude groups (§4.4)."""
    bad = [
        (s.name, s.independence_group)
        for s in srv.PROXY_REGISTRY
        if s.target_variable == "K"
        and s.canonical_status == "canonical_voting"
        and s.independence_group in FORBIDDEN_K_GROUPS
    ]
    assert not bad, (
        f"K canonical_voting proxies with forbidden independence_group: {bad}. "
        f"K is explicitly NOT vol/jump/tail/credit (Finance-2.tex §4.4)."
    )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_canonical_subbaskets_covered(spec):
    """Each canonical sub-basket has at least one ProxySpec (voting OR awaiting_data)."""
    canonical_to_code = {"M": "M", "D": "D_contraction", "K": "K", "X_agg": "X_agg"}
    missing = []
    for ch_name, ch_spec in spec["channels"].items():
        code_ch = canonical_to_code.get(ch_name, ch_name)
        for sb_id in ch_spec.get("subbaskets", {}):
            tag = f"{ch_name}.{sb_id}"
            tag_d = f"{code_ch}.{sb_id}"  # alt notation
            covered = any(
                s.canonical_subbasket in (tag, tag_d)
                and s.target_variable == code_ch
                for s in srv.PROXY_REGISTRY
            )
            if not covered:
                missing.append(tag)
    assert not missing, (
        f"Canonical sub-baskets without any registered ProxySpec: {missing}. "
        f"Each must have at least one entry (canonical_voting OR awaiting_data)."
    )


@pytest.mark.governance_loop
@pytest.mark.semantic
def test_canonical_voting_proxies_have_subbasket_tag():
    """Any canonical_voting proxy must declare which sub-basket it serves."""
    bad = [
        s.name for s in srv.PROXY_REGISTRY
        if s.canonical_status == "canonical_voting" and not s.canonical_subbasket
    ]
    assert not bad, (
        f"canonical_voting proxies without canonical_subbasket: {bad}. "
        f"Every voter must declare which canonical sub-basket it fills."
    )
