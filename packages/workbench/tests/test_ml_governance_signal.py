"""Tests for ml.governance_signal — semantic + authority → ML signal pipeline."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.governance_signal import (
    _concept_score,
    _severity_to_regime,
    build_semantic_signal,
    build_authority_signal,
)

# ---------------------------------------------------------------------------
# Sample registry data
# ---------------------------------------------------------------------------

SAMPLE_SEMANTIC = {
    "M": {
        "implemented_status": "IMPLEMENTED",
        "proxy_status": "DIRECT_PROXY",
        "semantic_distance": 0,
        "operational_proxy": "NFCI",
        "reduction_errors": ["sampling error at high freq"],
        "valid_for": ["broad stress"],
        "not_valid_for": ["idiosyncratic shocks"],
    },
    "D": {
        "implemented_status": "IMPLEMENTED",
        "proxy_status": "WEAK_PROXY",
        "semantic_distance": 2,
        "operational_proxy": "STLFSI4",
        "reduction_errors": ["lag bias"],
        "valid_for": ["degrees-of-freedom stress"],
        "not_valid_for": ["liquidity crises"],
    },
    "X_PRE": {
        "implemented_status": "IMPLEMENTED",
        "proxy_status": "DISTANT_PROXY",
        "semantic_distance": 3,
        "operational_proxy": "BAMLH0A0HYM2",
        "reduction_errors": ["ratings migration noise", "duration mismatch"],
        "valid_for": ["credit channel pre-crisis"],
        "not_valid_for": ["acute liquidity events", "sovereign stress"],
    },
    "UNIMPLEMENTED": {
        "implemented_status": "NOT_IMPLEMENTED",
        "proxy_status": "NO_PROXY",
        "semantic_distance": None,
        "operational_proxy": None,
        "reduction_errors": [],
        "valid_for": [],
        "not_valid_for": [],
    },
}


def _write_semantic_registry(tmp_path: Path) -> Path:
    path = tmp_path / "semantic_registry.json"
    path.write_text(json.dumps(SAMPLE_SEMANTIC, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _concept_score
# ---------------------------------------------------------------------------

class TestConceptScore:
    def test_not_implemented_returns_zero(self):
        meta = SAMPLE_SEMANTIC["UNIMPLEMENTED"]
        assert _concept_score(meta) == 0.0

    def test_distance_zero_returns_one(self):
        meta = SAMPLE_SEMANTIC["M"]
        assert _concept_score(meta) == 1.0

    def test_distance_two_returns_05(self):
        meta = SAMPLE_SEMANTIC["D"]
        assert _concept_score(meta) == 0.5

    def test_distance_three_returns_025(self):
        meta = SAMPLE_SEMANTIC["X_PRE"]
        assert _concept_score(meta) == 0.25

    def test_distance_four_or_more(self):
        meta = dict(SAMPLE_SEMANTIC["X_PRE"], semantic_distance=5)
        assert _concept_score(meta) == 0.1


# ---------------------------------------------------------------------------
# _severity_to_regime
# ---------------------------------------------------------------------------

class TestSeverityToRegime:
    def test_ok_is_compression(self):
        assert _severity_to_regime("OK") == "compression"

    def test_critical_is_crisis(self):
        assert _severity_to_regime("CRITICAL") == "crisis"

    def test_high_is_volatile(self):
        assert _severity_to_regime("HIGH") == "volatile"


# ---------------------------------------------------------------------------
# build_semantic_signal
# ---------------------------------------------------------------------------

class TestBuildSemanticSignal:
    def test_payload_has_required_keys(self, tmp_path):
        reg_path = _write_semantic_registry(tmp_path)
        payload = build_semantic_signal(reg_path, write=False)
        for key in ("schema_version", "signal_type", "generated_at", "source_release", "method", "factors", "freshness_gate"):
            assert key in payload

    def test_signal_type_is_factor(self, tmp_path):
        reg_path = _write_semantic_registry(tmp_path)
        payload = build_semantic_signal(reg_path, write=False)
        assert payload["signal_type"] == "factor"

    def test_factors_match_concepts(self, tmp_path):
        reg_path = _write_semantic_registry(tmp_path)
        payload = build_semantic_signal(reg_path, write=False)
        factor_ids = {f["id"] for f in payload["factors"]}
        assert factor_ids == {"M", "D", "X_PRE", "UNIMPLEMENTED"}

    def test_not_implemented_has_zero_score(self, tmp_path):
        reg_path = _write_semantic_registry(tmp_path)
        payload = build_semantic_signal(reg_path, write=False)
        for f in payload["factors"]:
            if f["id"] == "UNIMPLEMENTED":
                assert f["score"] == 0.0

    def test_writes_signal_file(self, tmp_path):
        reg_path = _write_semantic_registry(tmp_path)
        out_root = tmp_path / "ml_signals"
        payload = build_semantic_signal(reg_path, output_root=out_root, write=True)
        signal_dir = out_root / payload["source_release"]
        assert (signal_dir / "governance_semantic.json").exists()
        assert (signal_dir / "manifest.json").exists()

    def test_freshness_gate_valid(self, tmp_path):
        reg_path = _write_semantic_registry(tmp_path)
        payload = build_semantic_signal(reg_path, write=False)
        assert payload["freshness_gate"]["stale_if_release_changes"] is True
        assert payload["freshness_gate"]["signal_valid"] is True

    def test_custom_source_release(self, tmp_path):
        reg_path = _write_semantic_registry(tmp_path)
        payload = build_semantic_signal(reg_path, source_release="custom_rel", write=False)
        assert payload["source_release"] == "custom_rel"


# ---------------------------------------------------------------------------
# build_authority_signal
# ---------------------------------------------------------------------------

SAMPLE_AUTHORITY = {
    "violations": [
        {"rule_id": "boundary_001", "severity": "LOW", "reason": "Minor boundary"},
        {"rule_id": "boundary_002", "severity": "MEDIUM", "reason": "Moderate issue"},
        {"rule_id": "boundary_003", "severity": "HIGH", "reason": "Significant violation"},
    ]
}

SAMPLE_AUTHORITY_CRITICAL = {
    "violations": [
        {"rule_id": "crit_001", "severity": "CRITICAL", "reason": "Fatal violation"},
        {"rule_id": "crit_002", "severity": "CRITICAL", "reason": "Another critical"},
        {"rule_id": "crit_003", "severity": "LOW", "reason": "Minor"},
    ]
}

SAMPLE_AUTHORITY_CLEAN = {
    "violations": [
        {"rule_id": "ok_001", "severity": "OK", "reason": "All clear"},
    ]
}


def _write_authority_registry(tmp_path: Path, data: dict | None = None) -> Path:
    path = tmp_path / "authority_registry.json"
    path.write_text(json.dumps(data or SAMPLE_AUTHORITY, indent=2), encoding="utf-8")
    return path


class TestBuildAuthoritySignal:
    def test_payload_has_required_keys(self, tmp_path):
        auth_path = _write_authority_registry(tmp_path)
        payload = build_authority_signal(auth_path, write=False)
        for key in ("schema_version", "signal_type", "generated_at", "regime", "freshness_gate"):
            assert key in payload

    def test_signal_type_is_regime(self, tmp_path):
        auth_path = _write_authority_registry(tmp_path)
        payload = build_authority_signal(auth_path, write=False)
        assert payload["signal_type"] == "regime"

    def test_high_severity_gives_volatile(self, tmp_path):
        auth_path = _write_authority_registry(tmp_path)
        payload = build_authority_signal(auth_path, write=False)
        assert payload["regime"]["current"] == "volatile"

    def test_critical_gives_crisis(self, tmp_path):
        auth_path = _write_authority_registry(tmp_path, SAMPLE_AUTHORITY_CRITICAL)
        payload = build_authority_signal(auth_path, write=False)
        assert payload["regime"]["current"] == "crisis"

    def test_clean_gives_compression(self, tmp_path):
        auth_path = _write_authority_registry(tmp_path, SAMPLE_AUTHORITY_CLEAN)
        payload = build_authority_signal(auth_path, write=False)
        assert payload["regime"]["current"] == "compression"

    def test_state_probs_sum_to_one(self, tmp_path):
        auth_path = _write_authority_registry(tmp_path)
        payload = build_authority_signal(auth_path, write=False)
        total = sum(payload["regime"]["state_probs"].values())
        assert abs(total - 1.0) < 0.02

    def test_writes_signal_file(self, tmp_path):
        auth_path = _write_authority_registry(tmp_path)
        out_root = tmp_path / "ml_signals"
        payload = build_authority_signal(auth_path, output_root=out_root, write=True)
        signal_dir = out_root / payload["source_release"]
        assert (signal_dir / "governance_authority.json").exists()
        assert (signal_dir / "manifest.json").exists()
