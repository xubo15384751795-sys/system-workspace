"""Governance Runtime Contracts — validate ACTIVE_RUNTIME governance files.

These 5 files are loaded by active scripts at runtime but previously
had no test coverage. This contract suite ensures they are well-formed
and structurally valid.

Files tested:
- operator_registry.yaml (loaded by daily_run.py, operator_registry_audit.py)
- position_sizing_policy.yaml (loaded by position_sizing_layer.py)
- run_mode_registry.yaml (loaded by run_work_cycle.py)
- opencode_supervisor_policy.yaml (loaded by run_supervisor_check.py)
- incentive_policy.yaml (loaded by build_incentive_review.py)
"""
from __future__ import annotations

import yaml
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"


def _load(name: str) -> dict:
    return yaml.safe_load((GOV / name).read_text(encoding="utf-8"))


# ── operator_registry.yaml ──────────────────────────────────────────────────

class TestOperatorRegistry:
    REG = _load("operator_registry.yaml")

    def test_schema_version(self):
        assert "schema_version" in self.REG
        assert "operator_registry" in self.REG["schema_version"]

    def test_has_operators(self):
        assert "operators" in self.REG
        assert len(self.REG["operators"]) > 0

    def test_operator_required_fields(self):
        required = {"type", "description", "inputs", "outputs", "claim_ceiling"}
        for name, op in self.REG["operators"].items():
            missing = required - set(op.keys())
            assert not missing, f"Operator '{name}' missing: {missing}"

    def test_operator_types_valid(self):
        valid_types = {
            "data_acquisition", "world_model", "event_radar",
            "measurement_operator", "measurement_gate", "state_recognition",
            "state_recognition_gate", "case_matching", "judgment_operator",
            "gate", "uncertainty_operator", "decision_operator",
            "position_operator", "calibration_operator", "output_assembly",
        }
        for name, op in self.REG["operators"].items():
            assert op["type"] in valid_types, f"Operator '{name}' has invalid type: {op['type']}"


# ── position_sizing_policy.yaml ─────────────────────────────────────────────

class TestPositionSizingPolicy:
    POL = _load("position_sizing_policy.yaml")

    def test_schema_version(self):
        assert "position_sizing" in self.POL["schema_version"]

    def test_hard_blocks_all_zero(self):
        for key, val in self.POL["hard_blocks"].items():
            assert val == "zero_position", f"hard_blocks.{key} should be zero_position"

    def test_decision_mapping_complete(self):
        expected = {"NO_TRADE", "WATCH", "RISK_REDUCE", "HEDGE", "TACTICAL_LONG", "TACTICAL_SHORT"}
        actual = set(self.POL["decision_mapping"].keys())
        assert expected == actual, f"Missing: {expected - actual}, Extra: {actual - expected}"

    def test_decision_mapping_fields(self):
        for name, dm in self.POL["decision_mapping"].items():
            assert len(dm) > 0, f"Decision '{name}' is empty"

    def test_risk_unit_defined(self):
        ru = self.POL["risk_unit"]
        assert "max_risk_per_trade" in ru
        assert "max_portfolio_risk" in ru


# ── run_mode_registry.yaml ──────────────────────────────────────────────────

class TestRunModeRegistry:
    REG = _load("run_mode_registry.yaml")

    def test_schema_version(self):
        assert "run_mode" in self.REG["schema_version"]

    def test_modes_defined(self):
        expected = {"quick_reaction", "standard_run", "full_refresh"}
        actual = set(self.REG["modes"].keys())
        assert expected == actual

    def test_mode_required_fields(self):
        required = {"purpose", "expected_seconds", "steps", "writes"}
        for name, mode in self.REG["modes"].items():
            missing = required - set(mode.keys())
            assert not missing, f"Mode '{name}' missing: {missing}"

    def test_work_brief_sections(self):
        sections = self.REG.get("work_brief_sections", [])
        assert len(sections) > 0
        for s in sections:
            assert "id" in s
            assert "question" in s


# ── opencode_supervisor_policy.yaml ─────────────────────────────────────────

class TestSupervisorPolicy:
    POL = _load("opencode_supervisor_policy.yaml")

    def test_schema_version(self):
        assert "opencode_supervisor" in self.POL["schema_version"]

    def test_responsibilities_defined(self):
        resps = self.POL["responsibilities"]
        assert len(resps) > 0
        for r in resps:
            assert "id" in r
            assert "description" in r
            assert "check" in r

    def test_output_paths_defined(self):
        output = self.POL["output"]
        assert "markdown" in output
        assert "json" in output

    def test_review_queue_sources_match_responsibilities(self):
        resp_ids = {r["id"] for r in self.POL["responsibilities"]}
        queue_sources = set(self.POL["review_queue"]["sources"])
        unknown = queue_sources - resp_ids
        assert not unknown, f"Review queue references unknown responsibilities: {unknown}"


# ── incentive_policy.yaml ───────────────────────────────────────────────────

class TestIncentivePolicy:
    POL = _load("incentive_policy.yaml")

    def test_schema_version(self):
        assert "incentive" in self.POL["schema_version"]

    def test_priority_levels(self):
        expected = {"low", "registered", "preferred", "canonical"}
        actual = set(self.POL["priority_levels"].keys())
        assert expected == actual

    def test_priority_level_fields(self):
        required = {"meaning", "visibility", "can_enter_current", "can_affect_core_judgment"}
        for name, level in self.POL["priority_levels"].items():
            missing = required - set(level.keys())
            assert not missing, f"Priority '{name}' missing: {missing}"

    def test_credit_sources_have_points(self):
        for name, src in self.POL["credit_sources"].items():
            assert "points" in src, f"Credit source '{name}' missing points"
            assert "rule" in src, f"Credit source '{name}' missing rule"

    def test_anti_gaming_defined(self):
        ag = self.POL["anti_gaming"]
        assert "not_rewarded" in ag
        assert "rewarded" in ag
        assert len(ag["not_rewarded"]) > 0
