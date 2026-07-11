"""Channel Contributors — tests for per-proxy contribution breakdown.

Verifies that framework_output.json includes per-channel contributor
data and that signal_card.md displays it correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# ── Contributor extraction tests ─────────────────────────────────────────────

def _make_registry():
    """Sample proxy registry entries."""
    return [
        {
            "name": "M_policy_bill_gap",
            "channel": "M",
            "target_variable": "M",
            "tier": "auxiliary",
            "canonical_status": "canonical_voting",
            "proxy_status": "PROXY_REDUCED",
            "raw_series": ["FRED:DFF", "FRED:DGS3MO"],
            "raw_family": "FRED_RATES",
            "mechanism": "policy_market_anchor_gap",
        },
        {
            "name": "M_curve_inversion",
            "channel": "M",
            "target_variable": "M",
            "tier": "diagnostic_only",
            "canonical_status": "quarantined_drift",
            "proxy_status": "PROXY_REDUCED",
            "raw_series": ["FRED:T10Y2Y"],
            "raw_family": "FRED_RATES",
            "mechanism": "anchor_mismatch",
        },
        {
            "name": "D_cp_bill_funding_access",
            "channel": "D",
            "target_variable": "D",
            "tier": "core",
            "canonical_status": "canonical_voting",
            "proxy_status": "PROXY_REDUCED",
            "raw_series": ["FRED:DCPF3M", "FRED:DGS3MO"],
            "raw_family": "FRED_FUNDING",
            "mechanism": "funding_access",
        },
    ]


def _make_components():
    """Sample proxy_components DataFrame."""
    dates = pd.date_range("2026-06-15", periods=4, freq="D")
    return pd.DataFrame({
        "M_policy_bill_gap": [-1.90, -1.95, -2.00, -2.09],
        "M_curve_inversion": [2.10, 2.15, 2.20, 2.27],
        "D_cp_bill_funding_access": [-0.60, -0.65, -0.70, -0.76],
    }, index=dates)


def test_contributors_sorted_by_abs_zscore():
    """Contributors are sorted by absolute z-score descending."""
    from bridge_replay_to_current import _build_channel_contributors

    registry = _make_registry()
    components = _make_components()

    # Monkey-patch the file reads
    import bridge_replay_to_current as mod
    original_dir = mod.REPLAY_DIR

    import json as json_mod
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "proxy_registry.json").write_text(json_mod.dumps(registry))
        components.to_parquet(td_path / "proxy_components.parquet")

        mod.REPLAY_DIR = td_path
        try:
            result = _build_channel_contributors()
        finally:
            mod.REPLAY_DIR = original_dir

    assert "M" in result
    m_contributors = result["M"]
    assert len(m_contributors) == 2
    # Curve inversion (z=2.27) should come before policy_bill_gap (z=-2.09)
    assert m_contributors[0]["proxy_name"] == "M_curve_inversion"
    assert m_contributors[1]["proxy_name"] == "M_policy_bill_gap"


def test_contributors_have_required_fields():
    """Each contributor dict has all required fields."""
    from bridge_replay_to_current import _build_channel_contributors

    registry = _make_registry()
    components = _make_components()

    import bridge_replay_to_current as mod
    original_dir = mod.REPLAY_DIR

    import json as json_mod
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "proxy_registry.json").write_text(json_mod.dumps(registry))
        components.to_parquet(td_path / "proxy_components.parquet")

        mod.REPLAY_DIR = td_path
        try:
            result = _build_channel_contributors()
        finally:
            mod.REPLAY_DIR = original_dir

    for ch, contributors in result.items():
        for c in contributors:
            assert "proxy_name" in c
            assert "raw_series" in c
            assert "z_score" in c
            assert "direction" in c
            assert "tier" in c
            assert "canonical_status" in c
            assert "proxy_status" in c
            assert "harvester_sourced" in c


def test_harvester_sourced_detection():
    """FRED/SEC/OFR series are detected as Harvester sourced."""
    from bridge_replay_to_current import _build_channel_contributors

    registry = _make_registry()
    components = _make_components()

    import bridge_replay_to_current as mod
    original_dir = mod.REPLAY_DIR

    import json as json_mod
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "proxy_registry.json").write_text(json_mod.dumps(registry))
        components.to_parquet(td_path / "proxy_components.parquet")

        mod.REPLAY_DIR = td_path
        try:
            result = _build_channel_contributors()
        finally:
            mod.REPLAY_DIR = original_dir

    # All test proxies use FRED: series → should be harvester_sourced
    for ch, contributors in result.items():
        for c in contributors:
            assert c["harvester_sourced"] is True


def test_direction_classification():
    """Z-score sign maps to correct direction."""
    from bridge_replay_to_current import _build_channel_contributors

    registry = _make_registry()
    components = _make_components()

    import bridge_replay_to_current as mod
    original_dir = mod.REPLAY_DIR

    import json as json_mod
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "proxy_registry.json").write_text(json_mod.dumps(registry))
        components.to_parquet(td_path / "proxy_components.parquet")

        mod.REPLAY_DIR = td_path
        try:
            result = _build_channel_contributors()
        finally:
            mod.REPLAY_DIR = original_dir

    # M_policy_bill_gap z=-2.09 → negative
    m_pbg = [c for c in result["M"] if c["proxy_name"] == "M_policy_bill_gap"][0]
    assert m_pbg["direction"] == "negative"

    # M_curve_inversion z=+2.27 → positive
    m_ci = [c for c in result["M"] if c["proxy_name"] == "M_curve_inversion"][0]
    assert m_ci["direction"] == "positive"


def test_channel_grouping():
    """Proxies are grouped by their target channel."""
    from bridge_replay_to_current import _build_channel_contributors

    registry = _make_registry()
    components = _make_components()

    import bridge_replay_to_current as mod
    original_dir = mod.REPLAY_DIR

    import json as json_mod
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "proxy_registry.json").write_text(json_mod.dumps(registry))
        components.to_parquet(td_path / "proxy_components.parquet")

        mod.REPLAY_DIR = td_path
        try:
            result = _build_channel_contributors()
        finally:
            mod.REPLAY_DIR = original_dir

    assert len(result["M"]) == 2
    assert len(result["D"]) == 1
    assert "K" not in result
    assert "X_agg" not in result


def test_empty_components():
    """Empty components → empty result."""
    import bridge_replay_to_current as mod
    from bridge_replay_to_current import _build_channel_contributors
    original_dir = mod.REPLAY_DIR

    import json as json_mod
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "proxy_registry.json").write_text(json_mod.dumps(_make_registry()))
        pd.DataFrame().to_parquet(td_path / "proxy_components.parquet")

        mod.REPLAY_DIR = td_path
        try:
            result = _build_channel_contributors()
        finally:
            mod.REPLAY_DIR = original_dir

    assert result == {}


# ── Signal card markdown tests ──────────────────────────────────────────────

def test_signal_card_markdown_has_contributors():
    """Signal card markdown includes contributor section when data exists."""
    from build_signal_card import generate_markdown

    card = {
        "generated_at": "2026-06-18T00:00:00Z",
        "date": "2026-06-18",
        "schema_version": "signal_card.v1",
        "current_reaction": {
            "decision": "WATCH_ONLY",
            "confidence": "low",
            "claim_ceiling": "mechanism_hypothesis",
            "trade_decision": "NO_TRADE",
            "framework_status": "active_full",
        },
        "decision": "WATCH_ONLY",
        "confidence": {"level": "low"},
        "claim_ceiling": "mechanism_hypothesis",
        "trade_decision": "NO_TRADE",
        "framework_status": "active_full",
        "channel_decomposition": [
            {
                "channel": "M",
                "value": -2.092,
                "direction": "bearish",
                "size": "large",
                "confidence": "high",
                "primary_readout_eligible": True,
                "readout_class": "primary_readout",
                "framework_role": "canonical_dimension",
                "status_detail": "PROXY_REDUCED",
                "reason": "test",
                "contributors": [
                    {
                        "proxy_name": "M_policy_bill_gap",
                        "raw_series": ["FRED:DFF", "FRED:DGS3MO"],
                        "z_score": -2.09,
                        "direction": "negative",
                        "tier": "auxiliary",
                        "canonical_status": "canonical_voting",
                        "proxy_status": "PROXY_REDUCED",
                        "harvester_sourced": True,
                    },
                ],
            },
            {
                "channel": "K",
                "value": -0.161,
                "direction": "neutral",
                "size": "negligible",
                "confidence": "low",
                "primary_readout_eligible": False,
                "readout_class": "diagnostic_only",
                "framework_role": "canonical_dimension",
                "status_detail": "THEORY_RETAINED_MEASUREMENT_INCOMPLETE",
                "reason": "test",
                "contributors": [
                    {
                        "proxy_name": "K_credit_surface_HY_minus_IG",
                        "raw_series": ["FRED:BAMLH0A0HYM2", "FRED:BAMLC0A0CM"],
                        "z_score": -0.16,
                        "direction": "negative",
                        "tier": "diagnostic_only",
                        "canonical_status": "quarantined_drift",
                        "proxy_status": "PROXY_REDUCED",
                        "harvester_sourced": True,
                    },
                ],
            },
        ],
        "gate_classification": [],
        "evidence": [],
        "contributing_factors": [],
            "blockers": [],
            "counterfactuals": [],
            "confidence_reasons": [],
            "confidence_explanation": {"reasons": ["test"], "what_would_improve": []},
        }

    md = generate_markdown(card)

    # Should have the contributor section header
    assert "Channel Contributors" in md
    # Should show M contributors with raw series
    assert "M_policy_bill_gap" in md
    assert "FRED:DFF" in md
    # Should show K as quarantined
    assert "quarantined_drift" in md
