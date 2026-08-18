"""Phase 1.2: freshness single-source-of-truth tests.

Verifies MAX_AGE_HOURS is derived from configs/freshness_policy.yaml (not
hardcoded), so changing the policy changes the validator's behavior.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "packages" / "workbench" / "src"))


class TestFreshnessPolicySourced:
    def test_weekly_artifacts_are_schedule_advisory_off_monday(self, monkeypatch):
        import freshness_validator as fv

        tuesday = datetime(2026, 8, 18, tzinfo=UTC)
        monday = datetime(2026, 8, 17, tzinfo=UTC)
        assert fv._weekly_freshness_due(tuesday) is False
        assert fv._weekly_freshness_due(monday) is True
        monkeypatch.setenv("SYSTEM_FORCE_WEEKLY", "1")
        assert fv._weekly_freshness_due(tuesday) is True

    def test_max_age_hours_derived_from_policy(self):
        import freshness_validator as fv

        # daily acceptable_lag_days=10 -> 240h; weekly=21 -> 504h.
        assert fv.MAX_AGE_HOURS["harvester"] == 240  # daily
        assert fv.MAX_AGE_HOURS["learning_summary"] == 504  # weekly

    def test_no_hardcoded_max_age_hours_dict(self):
        """The old hardcoded dict must be gone; the policy loader is the source."""
        src = (ROOT / "scripts" / "freshness_validator.py").read_text(encoding="utf-8")
        # The old literal dict assignment must not be the definition.
        assert '"harvester": 48' not in src, (
            "hardcoded MAX_AGE_HOURS=48 must be removed; derive from policy"
        )
        assert "_load_max_age_hours_from_policy" in src

    def test_policy_change_changes_budget(self, tmp_path, monkeypatch):
        """If the policy yaml's acceptable_lag_days changes, the derived
        MAX_AGE_HOURS changes with it - proving the validator reads the policy."""
        import yaml

        # Write a temp policy with daily acceptable_lag_days=5.
        policy = tmp_path / "freshness_policy.yaml"
        policy.write_text(yaml.safe_dump({
            "frequency_thresholds": {
                "daily": {"fresh_lag_days": 2, "acceptable_lag_days": 5},
                "weekly": {"fresh_lag_days": 7, "acceptable_lag_days": 14},
            },
        }), encoding="utf-8")
        monkeypatch.setattr("freshness_validator._POLICY_PATH", policy)
        budgets = fv._load_max_age_hours_from_policy() if (fv := __import__("freshness_validator")) else {}
        # Reload to pick up patched path.
        import importlib

        import freshness_validator as fv2

        importlib.reload(fv2)
        fv2._POLICY_PATH = policy
        budgets = fv2._load_max_age_hours_from_policy()
        assert budgets["harvester"] == 5 * 24  # daily -> 120h
        assert budgets["learning_summary"] == 14 * 24  # weekly -> 336h
