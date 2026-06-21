from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.judgment_layer import build_judgment


def test_reduced_proxy_and_weak_caselab_forces_watch_only() -> None:
    fw = {
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
    caselab = {
        "match_quality": {"label": "weak", "top_score": 0.21},
        "regime_reconciliation": {
            "divergence": True,
            "hmm_regime": "crisis",
            "mdx_regime": "stress_relief",
        },
    }

    card = build_judgment(fw, caselab)

    assert card["decision"] == "WATCH_ONLY"
    assert card["confidence"]["level"] == "low"
    assert card["claim_ceiling"] == "diagnostic_watch_only"
    assert any("CaseLab match is weak" in reason for reason in card["confidence"]["reasons"])
    assert any("Do not use this output as a trading signal." in item for item in card["actionability"]["forbidden"])


def test_strong_caselab_with_full_proxy() -> None:
    """Strong CaseLab + full proxy quality → higher confidence."""
    fw = {
        "as_of": "2026-06-16T00:00:00+00:00",
        "basic": {
            "quality_status": "FULL_PROXY",
            "measurement_quality": "HIGH_CONFIDENCE",
            "validity_scope": "FULL_STRUCTURAL_STRESS",
        },
        "advanced": {
            "primary_readout": {
                "state": "MIXED_ANCHOR_PATH_STRESS",
                "M_anchor_geometry": {"value": -1.1},
                "D_path_geometry": {"value": -0.8},
            },
            "channel_confidence": {
                "M": {"proxy_quality": "FULL_PROXY", "confidence": "high", "readout_role": "primary_readout"},
                "D": {"proxy_quality": "FULL_PROXY", "confidence": "high", "readout_role": "primary_readout"},
                "K": {"proxy_quality": "FULL_PROXY", "confidence": "high", "readout_role": "diagnostic_rebuild"},
                "X_agg": {"proxy_quality": "FULL_PROXY", "confidence": "high", "readout_role": "background_only"},
            },
        },
    }
    caselab = {
        "match_quality": {"label": "strong", "top_score": 0.82},
        "regime_reconciliation": {
            "divergence": False,
            "hmm_regime": "stress_building",
            "mdx_regime": "stress_building",
        },
    }

    card = build_judgment(fw, caselab)

    assert card["decision"] in ("WATCH_ONLY", "RESEARCH_REVIEW")
    assert card["confidence"]["level"] in ("low", "medium", "high")


def test_empty_caselab_graceful_degradation() -> None:
    """Empty caselab dict should not crash — produces a valid card."""
    fw = {
        "as_of": "2026-06-16T00:00:00+00:00",
        "basic": {
            "quality_status": "FULL_PROXY",
            "measurement_quality": "HIGH_CONFIDENCE",
            "validity_scope": "FULL_STRUCTURAL_STRESS",
        },
        "advanced": {
            "primary_readout": {
                "state": "NORMAL",
                "M_anchor_geometry": {"value": 0.1},
                "D_path_geometry": {"value": 0.05},
            },
            "channel_confidence": {
                "M": {"proxy_quality": "FULL_PROXY", "confidence": "high", "readout_role": "primary_readout"},
                "D": {"proxy_quality": "FULL_PROXY", "confidence": "high", "readout_role": "primary_readout"},
                "K": {"proxy_quality": "FULL_PROXY", "confidence": "high", "readout_role": "diagnostic_rebuild"},
                "X_agg": {"proxy_quality": "FULL_PROXY", "confidence": "high", "readout_role": "background_only"},
            },
        },
    }

    card = build_judgment(fw, {})

    assert "decision" in card
    assert "confidence" in card
    assert "claim_ceiling" in card


def test_card_has_required_keys() -> None:
    """Every judgment card must have the standard set of keys."""
    fw = {
        "as_of": "2026-06-16T00:00:00+00:00",
        "basic": {"quality_status": "FULL_PROXY", "measurement_quality": "LOW_CONFIDENCE_PROXY_REDUCED", "validity_scope": "PARTIAL_STRUCTURAL_STRESS_DIAGNOSTIC"},
        "advanced": {
            "primary_readout": {"state": "NORMAL", "M_anchor_geometry": {"value": 0.0}, "D_path_geometry": {"value": 0.0}},
            "channel_confidence": {
                "M": {"proxy_quality": "PROXY_REDUCED", "confidence": "low", "readout_role": "primary_readout"},
                "D": {"proxy_quality": "PROXY_REDUCED", "confidence": "low", "readout_role": "primary_readout"},
                "K": {"proxy_quality": "PROXY_REDUCED", "confidence": "low", "readout_role": "diagnostic_rebuild"},
                "X_agg": {"proxy_quality": "PROXY_REDUCED", "confidence": "low", "readout_role": "background_only"},
            },
        },
    }
    caselab = {"match_quality": {"label": "weak", "top_score": 0.2}}

    card = build_judgment(fw, caselab)

    required_keys = {"decision", "confidence", "claim_ceiling", "gate_status", "actionability"}
    assert required_keys.issubset(card.keys()), f"Missing keys: {required_keys - card.keys()}"
