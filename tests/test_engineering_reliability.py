"""Tests for engineering reliability: false-fail prevention, closure chain,
confidence layering, and claim ladder integration."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Workbench" / "src"))


# ── refresh_etf_panel: false-fail prevention ──────────────────────────


class TestRefreshETFPanelNoFalseFail:
    """refresh_etf_panel.py must not raise SystemExit when panel is missing."""

    def test_check_panel_returns_false_when_missing(self, tmp_path):
        """check_panel() returns False (not raises) when panel is missing."""
        with patch("scripts.refresh_etf_panel.PANEL_PATH", tmp_path / "missing.parquet"):
            from scripts.refresh_etf_panel import check_panel
            result = check_panel()
            assert result is False

    def test_update_k_features_returns_false_when_script_missing(self, tmp_path):
        """update_k_features() returns False (not raises) when script is missing."""
        with patch("scripts.refresh_etf_panel.ROOT", tmp_path):
            from scripts.refresh_etf_panel import update_k_features
            result = update_k_features()
            assert result is False

    def test_main_returns_zero_when_panel_missing(self, tmp_path):
        """main() returns 0 even when panel is missing."""
        with patch("scripts.refresh_etf_panel.PANEL_PATH", tmp_path / "missing.parquet"):
            with patch("scripts.refresh_etf_panel.ROOT", tmp_path):
                from scripts.refresh_etf_panel import main
                result = main()
                assert result == 0


# ── Closure chain detection ───────────────────────────────────────────


class TestClosureChain:
    """Freshness validator detects partial refreshes."""

    def test_no_violation_when_all_current(self, tmp_path):
        """No closure violation when all current outputs are fresh."""
        now = datetime.now(UTC)
        for name in ["00_READ_ME_FIRST.md", "signal_card.json", "work_brief.json"]:
            p = tmp_path / "Output" / "current" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}")
            import os
            os.utime(p, (now.timestamp(), now.timestamp()))

        idx = tmp_path / "Data" / "system_index" / "latest.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text("{}")
        import os
        os.utime(idx, (now.timestamp(), now.timestamp()))

        with patch("scripts.freshness_validator.OUTPUT_DIR", tmp_path / "Output"):
            with patch("scripts.freshness_validator.ROOT", tmp_path):
                from scripts.freshness_validator import check_closure_chain
                issues = check_closure_chain(now)
                assert len(issues) == 0

    def test_violation_when_stale_artifact(self, tmp_path):
        """Closure violation when one artifact is 10 minutes older."""
        now = datetime.now(UTC)
        fresh = now
        stale = now - timedelta(minutes=10)

        for name, ts in [
            ("00_READ_ME_FIRST.md", fresh),
            ("signal_card.json", fresh),
            ("work_brief.json", stale),
        ]:
            p = tmp_path / "Output" / "current" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}")
            import os
            os.utime(p, (ts.timestamp(), ts.timestamp()))

        idx = tmp_path / "Data" / "system_index" / "latest.json"
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text("{}")
        import os
        os.utime(idx, (fresh.timestamp(), fresh.timestamp()))

        with patch("scripts.freshness_validator.OUTPUT_DIR", tmp_path / "Output"):
            with patch("scripts.freshness_validator.ROOT", tmp_path):
                from scripts.freshness_validator import check_closure_chain
                issues = check_closure_chain(now)
                assert len(issues) > 0
                assert "work_brief" in issues[0]["rule"]


# ── Confidence layering ──────────────────────────────────────────────


class TestConfidenceLayering:
    """Judgment card must include layered confidence."""

    def test_layered_confidence_in_judgment(self):
        """build_judgment returns diagnostic/mechanism/trade confidence."""
        judgment_path = ROOT / "Output" / "judgment" / "latest.json"
        if not judgment_path.exists():
            pytest.skip("No judgment card available")

        j = json.loads(judgment_path.read_text())
        conf = j.get("confidence", {})
        layered = conf.get("layered", {})

        assert "diagnostic_confidence" in layered, "Missing diagnostic_confidence"
        assert "mechanism_confidence" in layered, "Missing mechanism_confidence"
        assert "trade_confidence" in layered, "Missing trade_confidence"

        valid_levels = {"low", "medium_low", "medium", "medium_high", "high"}
        assert layered["diagnostic_confidence"] in valid_levels
        assert layered["mechanism_confidence"] in valid_levels
        assert layered["trade_confidence"] in valid_levels


# ── Claim ladder integration ─────────────────────────────────────────


class TestClaimLadderIntegration:
    """Claim ladder must be present in judgment card."""

    def test_claim_ladder_in_judgment(self):
        judgment_path = ROOT / "Output" / "judgment" / "latest.json"
        if not judgment_path.exists():
            pytest.skip("No judgment card available")

        j = json.loads(judgment_path.read_text())
        ladder = j.get("claim_ladder", {})

        assert "tier" in ladder, "Missing claim_ladder.tier"
        assert "label" in ladder, "Missing claim_ladder.label"
        assert "claim_statement" in ladder, "Missing claim_ladder.claim_statement"
        assert ladder["tier"] in (0, 1, 2, 3), f"Invalid tier: {ladder['tier']}"

    def test_claim_ladder_in_promotion_gate(self):
        gate_path = ROOT / "Output" / "judgment" / "promotion_gate.json"
        if not gate_path.exists():
            pytest.skip("No promotion gate available")

        g = json.loads(gate_path.read_text())
        ladder = g.get("claim_ladder")
        assert ladder is not None, "claim_ladder missing from promotion gate"
        assert "tier" in ladder


# ── HMM stability: model_health + calibration split ───────────────────


class TestHMMStabilitySplit:
    """HMM stability audit must include model_health and calibration_status."""

    def test_audit_has_split_dimensions(self):
        audit_path = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
        if not audit_path.exists():
            pytest.skip("No HMM audit available")

        a = json.loads(audit_path.read_text())

        assert "model_health" in a, "Missing model_health"
        assert "calibration_status" in a, "Missing calibration_status"
        assert "grade" in a["model_health"], "Missing model_health.grade"
        assert "status" in a["calibration_status"], "Missing calibration_status.status"

        assert a["model_health"]["grade"] in ("PASS", "WATCH", "FAIL")
        assert a["calibration_status"]["status"] in (
            "INSUFFICIENT_HISTORY", "CALIBRATING", "PASSED"
        )

    def test_hmm_supportable_claims(self):
        audit_path = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
        if not audit_path.exists():
            pytest.skip("No HMM audit available")

        a = json.loads(audit_path.read_text())
        supportable = a.get("hmm_supportable_claims", [])
        assert "mechanism_hypothesis" in supportable, "mechanism_hypothesis should be supportable"
        assert "watch_condition" in supportable, "watch_condition should be supportable"
