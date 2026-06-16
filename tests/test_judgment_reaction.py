"""Judgment output reaction tests.

Verifies that the judgment layer produces structured outputs with
decision, confidence, claim_ceiling, and gate_status.
See: governance/architecture_reality_decisions.md §7

Note: The "reaction" format (bottlenecks, next_best_actions, basis) is a
future enhancement tracked in the architecture reality decisions. Current
tests verify the existing output shape.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.judgment_layer import build_judgment


def _make_framework_output() -> dict:
    """Minimal framework output for testing."""
    return {
        "as_of": "2026-06-16T00:00:00+00:00",
        "basic": {
            "quality_status": "FULL_PROXY_REDUCED",
            "measurement_quality": "LOW_CONFIDENCE_PROXY_REDUCED",
            "validity_scope": "PARTIAL_STRUCTURAL_STRESS_DIAGNOSTIC",
        },
        "advanced": {
            "primary_readout": {
                "state": "MIXED_ANCHOR_PATH_STRESS",
                "M_anchor_geometry": {"value": -1.1},
                "D_path_geometry": {"value": -0.8},
            },
            "channel_confidence": {
                "M": {"proxy_quality": "PROXY_REDUCED", "confidence": "low", "readout_role": "primary_readout"},
                "D": {"proxy_quality": "PROXY_REDUCED", "confidence": "low", "readout_role": "primary_readout"},
                "K": {"proxy_quality": "PROXY_REDUCED", "confidence": "low", "readout_role": "diagnostic_rebuild"},
                "X_agg": {"proxy_quality": "PROXY_REDUCED", "confidence": "low", "readout_role": "background_only"},
            },
        },
    }


def _make_caselab() -> dict:
    """Minimal CaseLab for testing."""
    return {
        "match_quality": {"label": "weak", "top_score": 0.21},
        "regime_reconciliation": {
            "divergence": True,
            "hmm_regime": "crisis",
            "mdx_regime": "stress_relief",
        },
    }


def test_judgment_has_decision_field() -> None:
    """Judgment card must have a decision field."""
    card = build_judgment(_make_framework_output(), _make_caselab())
    assert "decision" in card, "Judgment card missing 'decision' field"
    assert isinstance(card["decision"], str)


def test_judgment_decision_is_valid() -> None:
    """Decision must be one of the known values."""
    card = build_judgment(_make_framework_output(), _make_caselab())
    valid_decisions = {"WATCH_ONLY", "RESEARCH_REVIEW", "ACTIVE_WATCH"}
    assert card["decision"] in valid_decisions, (
        f"Unknown decision: {card['decision']}"
    )


def test_judgment_has_confidence_field() -> None:
    """Judgment card must have confidence with level and reasons."""
    card = build_judgment(_make_framework_output(), _make_caselab())
    assert "confidence" in card, "Judgment card missing 'confidence' field"
    assert "level" in card["confidence"], "confidence missing 'level'"
    assert "reasons" in card["confidence"], "confidence missing 'reasons'"
    assert isinstance(card["confidence"]["reasons"], list)


def test_judgment_has_claim_ceiling() -> None:
    """Judgment card must have a claim_ceiling field."""
    card = build_judgment(_make_framework_output(), _make_caselab())
    assert "claim_ceiling" in card, "Judgment card missing 'claim_ceiling' field"
    assert isinstance(card["claim_ceiling"], str)


def test_judgment_has_gate_status() -> None:
    """Judgment card must have gate_status with sub-gates."""
    card = build_judgment(_make_framework_output(), _make_caselab())
    assert "gate_status" in card, "Judgment card missing 'gate_status' field"
    gate = card["gate_status"]
    assert isinstance(gate, dict)
    # Must have at least these sub-gates
    for key in ("hmm_stability", "k_gate", "x_gate", "quality_validation"):
        assert key in gate, f"gate_status missing '{key}'"


def test_judgment_has_actionability() -> None:
    """Judgment card must have actionability with allowed and forbidden."""
    card = build_judgment(_make_framework_output(), _make_caselab())
    assert "actionability" in card, "Judgment card missing 'actionability' field"
    assert "allowed" in card["actionability"]
    assert "forbidden" in card["actionability"]
    assert isinstance(card["actionability"]["forbidden"], list)


def test_judgment_has_schema_version() -> None:
    """Judgment card must have schema_version."""
    card = build_judgment(_make_framework_output(), _make_caselab())
    assert "schema_version" in card
    assert card["schema_version"] == "system.judgment_card.v1"
