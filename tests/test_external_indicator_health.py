"""Phase 2.2: external indicator health ledger tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _external_indicator_health import (  # noqa: E402
    failing_indicators,
    record_indicator_outcomes,
)


class TestExternalIndicatorHealth:
    def test_success_resets_failures(self, tmp_path):
        ledger = tmp_path / "health.json"
        record_indicator_outcomes(
            {"SRISK": {"success": False, "error": "429", "date": "2026-07-10"}},
            path=ledger,
        )
        record_indicator_outcomes(
            {"SRISK": {"success": True, "error": "", "date": "2026-07-11"}},
            path=ledger,
        )
        data = json.loads(ledger.read_text(encoding="utf-8"))
        assert data["SRISK"]["consecutive_failures"] == 0
        assert data["SRISK"]["last_success"] == "2026-07-11"
        assert data["SRISK"]["last_error"] == ""

    def test_failure_increments_count(self, tmp_path):
        ledger = tmp_path / "health.json"
        for d in ("2026-07-10", "2026-07-11", "2026-07-12"):
            record_indicator_outcomes(
                {"SRISK": {"success": False, "error": "timeout", "date": d}},
                path=ledger,
            )
        data = json.loads(ledger.read_text(encoding="utf-8"))
        assert data["SRISK"]["consecutive_failures"] == 3
        assert data["SRISK"]["last_success"] == ""

    def test_failing_indicators_threshold(self, tmp_path):
        ledger = tmp_path / "health.json"
        # SRISK fails 8 days (>= 7 threshold), COVAR fails 3 (below).
        for d in range(8):
            record_indicator_outcomes(
                {"SRISK": {"success": False, "error": "429", "date": f"2026-07-{10+d:02d}"}},
                path=ledger,
            )
        for d in range(3):
            record_indicator_outcomes(
                {"COVAR": {"success": False, "error": "x", "date": f"2026-07-{10+d:02d}"}},
                path=ledger,
            )
        failing = failing_indicators(path=ledger)
        names = [f["name"] for f in failing]
        assert "SRISK" in names
        assert "COVAR" not in names

    def test_build_next_actions_surfaces_failing_indicator(self, tmp_path, monkeypatch):
        """determine_next_actions must include a HIGH action for an indicator
        failing >= 7 days."""
        import _external_indicator_health as eih

        ledger = tmp_path / "health.json"
        for d in range(8):
            eih.record_indicator_outcomes(
                {"SRISK": {"success": False, "error": "429", "date": f"2026-07-{10+d:02d}"}},
                path=ledger,
            )
        # Patch the module-level HEALTH_PATH so failing_indicators() (called
        # with no path arg inside build_next_actions) reads our temp ledger.
        monkeypatch.setattr(eih, "HEALTH_PATH", ledger)

        sys.path.insert(0, str(ROOT / "scripts" / "commands" / "weekly"))
        from build_next_actions import determine_next_actions

        status = {
            "promotion_gate": {"blocked_gates": []},
            "signals": {},
        }
        actions = determine_next_actions(status)
        high_actions = [a for a in actions if a["priority"] == "HIGH"]
        assert any("SRISK" in a["action"] for a in high_actions), (
            f"failing SRISK must surface as HIGH action, got {high_actions}"
        )
