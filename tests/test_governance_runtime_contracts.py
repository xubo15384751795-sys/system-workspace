"""Governance Runtime Contracts — validate ACTIVE_RUNTIME governance files.

These files are loaded by active scripts at runtime and must satisfy
structural and authority-boundary invariants.

Files tested:
- operator_registry.yaml (loaded by daily_run.py, operator_registry_audit.py)
- position_sizing_policy.yaml (loaded by position_sizing_layer.py)
- run_mode_registry.yaml (loaded by run_work_cycle.py)
- opencode_supervisor_policy.yaml (loaded by run_supervisor_check.py)
- incentive_policy.yaml (loaded by build_incentive_review.py)
- experimental_submission_registry.yaml (loaded by build_incentive_review.py)
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

    def test_boundary_check_responsibilities_present(self):
        """Supervisor must cover boundary checks for authority contamination and incentive overreach."""
        resp_ids = {r["id"] for r in self.POL["responsibilities"]}
        required_boundary = {
            "current_authority_contamination",
            "incentive_overreach",
            "priority_drift",
        }
        missing = required_boundary - resp_ids
        assert not missing, f"Missing boundary check responsibilities: {missing}"


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
        required = {"meaning", "visibility", "can_affect_core_judgment"}
        for name, level in self.POL["priority_levels"].items():
            missing = required - set(level.keys())
            assert not missing, f"Priority '{name}' missing: {missing}"

    def test_credit_sources_have_review_weight(self):
        for name, src in self.POL["credit_sources"].items():
            assert "review_weight" in src, f"Credit source '{name}' missing review_weight"
            assert "rule" in src, f"Credit source '{name}' missing rule"

    def test_anti_gaming_defined(self):
        ag = self.POL["anti_gaming"]
        assert "not_rewarded" in ag
        assert "rewarded" in ag
        assert len(ag["not_rewarded"]) > 0

    # ── Authority Boundary Invariants ─────────────────────────────────────

    def test_authority_boundary_declared(self):
        """Authority boundary section must exist."""
        assert "authority_boundary" in self.POL, "Missing authority_boundary section"

    def test_credit_never_grants_authority(self):
        """Credit must never grant authority — this is the core invariant."""
        ab = self.POL["authority_boundary"]
        assert ab.get("credit_never_grants_authority") is True, \
            "credit_never_grants_authority must be true"

    def test_governance_cannot_grant_core_authority(self):
        """Governance cannot grant core authority — only code wiring can."""
        ab = self.POL["authority_boundary"]
        assert ab.get("governance_can_grant_core_authority") is False, \
            "governance_can_grant_core_authority must be false"

    def test_canonical_requires_runtime_wiring(self):
        """Canonical authority requires runtime wiring, not just policy."""
        ab = self.POL["authority_boundary"]
        assert ab.get("canonical_authority_requires_runtime_wiring") is True, \
            "canonical_authority_requires_runtime_wiring must be true"

    def test_preferred_cannot_affect_core_judgment(self):
        """Preferred status must NOT allow affecting core judgment."""
        preferred = self.POL["priority_levels"]["preferred"]
        assert preferred.get("can_affect_core_judgment") is False, \
            "preferred must not affect core judgment"

    def test_preferred_cannot_enter_authority_current(self):
        """Preferred status must NOT allow entering authority current."""
        preferred = self.POL["priority_levels"]["preferred"]
        # Check both old and new field names for compatibility
        can_enter = preferred.get("can_enter_authority_current",
                                  preferred.get("can_enter_current", True))
        assert can_enter is False, \
            "preferred must not enter authority current"

    def test_only_canonical_can_affect_core_judgment(self):
        """Only canonical level can affect core judgment."""
        for name, level in self.POL["priority_levels"].items():
            if name == "canonical":
                assert level["can_affect_core_judgment"] is True
            else:
                assert level["can_affect_core_judgment"] is False, \
                    f"'{name}' should not affect core judgment"

    def test_credit_sources_never_suggest_canonical(self):
        """Credit sources must never directly suggest canonical status."""
        for name, src in self.POL["credit_sources"].items():
            suggests = src.get("suggests_review_for", src.get("promotes_to", ""))
            assert suggests != "canonical", \
                f"Credit source '{name}' must not suggest canonical — canonical requires code wiring"
            assert suggests != "canonical_candidate", \
                f"Credit source '{name}' must not suggest canonical_candidate"

    def test_review_outcomes_no_automatic_promotion(self):
        """Review outcomes must not include automatic promotion to canonical."""
        outcomes = self.POL.get("review_outcomes", [])
        for outcome in outcomes:
            assert "promote_to_canonical" not in outcome, \
                f"Review outcome '{outcome}' implies automatic canonical promotion"

    def test_governance_can_veto(self):
        """Governance must have veto power."""
        ab = self.POL["authority_boundary"]
        assert ab.get("governance_can_veto") is True, \
            "governance_can_veto must be true"


# ── experimental_submission_registry.yaml ────────────────────────────────

class TestExperimentalSubmissionRegistry:
    REG = _load("experimental_submission_registry.yaml")

    def test_schema_version(self):
        assert "experimental_submission" in self.REG["schema_version"]

    def test_required_fields_defined(self):
        """Registry must declare required_fields for submissions."""
        assert "required_fields" in self.REG, "Missing required_fields section"
        rf = self.REG["required_fields"]
        assert len(rf) > 0, "required_fields is empty"
        # Must include key governance fields
        assert "submission_id" in rf
        assert "owner" in rf
        assert "rollback_plan" in rf
        assert "retire_after" in rf

    def test_allowed_decisions_defined(self):
        """Registry must declare allowed_decisions."""
        assert "allowed_decisions" in self.REG, "Missing allowed_decisions section"
        decisions = self.REG["allowed_decisions"]
        assert len(decisions) > 0

    def test_no_promote_to_canonical_in_decisions(self):
        """Canonical must NOT be an allowed decision — it requires code wiring."""
        decisions = self.REG.get("allowed_decisions", [])
        assert "promote_to_canonical" not in decisions, \
            "promote_to_canonical must not be an allowed decision — canonical requires code wiring"
        assert "promote_to_canonical_candidate" not in decisions

    def test_update_rule_proposal_allowed(self):
        """update_rule_proposal should be an allowed decision."""
        decisions = self.REG.get("allowed_decisions", [])
        assert "update_rule_proposal" in decisions, \
            "update_rule_proposal must be an allowed decision"

    def test_submission_types_include_topology_change(self):
        types = self.REG.get("submission_types", [])
        assert "topology_change" in types
        assert "exploration" in types


# ── authority_graph_policy.yaml ───────────────────────────────────────────

class TestAuthorityGraphPolicy:
    POL = _load("authority_graph_policy.yaml")

    def test_schema_version(self):
        assert "authority_graph_policy" in self.POL["schema_version"]

    def test_zones_defined(self):
        zones = self.POL.get("zones", {})
        for zone_id in ("Z0", "Z1", "Z2", "Z3", "Z_inf"):
            assert zone_id in zones

    def test_bridge_nodes_declared(self):
        assert "bridge" in self.POL.get("bridge_nodes", [])

    def test_graph_invariants_declared(self):
        invariants = self.POL.get("graph_invariants", [])
        ids = {item["id"] for item in invariants}
        assert "sandbox_requires_bridge" in ids
        assert "declared_derived_alignment" in ids


# ── pipeline_test_baseline.yaml ──────────────────────────────────────────

class TestPipelineTestBaseline:
    REG = _load("pipeline_test_baseline.yaml")

    def test_schema_version(self):
        assert "pipeline_test_baseline" in self.REG["schema_version"]

    def test_no_promotes_to(self):
        """Trust credits must use suggests_review_for, not promotes_to."""
        import yaml as _yaml
        raw = (GOV / "pipeline_test_baseline.yaml").read_text(encoding="utf-8")
        assert "promotes_to" not in raw, \
            "pipeline_test_baseline.yaml must not contain promotes_to — use suggests_review_for"

    def test_no_canonical_candidate(self):
        """Trust credits must not reference canonical_candidate."""
        import yaml as _yaml
        raw = (GOV / "pipeline_test_baseline.yaml").read_text(encoding="utf-8")
        assert "canonical_candidate" not in raw, \
            "pipeline_test_baseline.yaml must not reference canonical_candidate — use preferred"

    def test_trust_credits_use_review_weight(self):
        """Trust credits must use review_weight, not points."""
        for credit in self.REG.get("trust_credits", []):
            assert "review_weight" in credit, \
                f"Trust credit '{credit.get('source')}' missing review_weight"
            assert "points" not in credit, \
                f"Trust credit '{credit.get('source')}' still uses 'points' — use review_weight"

    def test_trust_credits_suggest_review_not_canonical(self):
        """Trust credits must not suggest canonical status."""
        for credit in self.REG.get("trust_credits", []):
            suggests = credit.get("suggests_review_for", "")
            assert suggests != "canonical", \
                f"Trust credit '{credit.get('source')}' must not suggest canonical"
            assert suggests != "canonical_candidate", \
                f"Trust credit '{credit.get('source')}' must not suggest canonical_candidate"


# ── system_constitution.yaml ─────────────────────────────────────────────

class TestSystemConstitution:
    CONST = _load("system_constitution.yaml")

    def test_schema_version(self):
        assert "system_constitution" in self.CONST["schema_version"]

    def test_prohibited_from_core_judgment(self):
        """Constitution must declare prohibited output paths."""
        har = self.CONST.get("hard_authority_rule", {})
        prohibited = har.get("prohibited_from_core_judgment", [])
        assert "Output/sandbox/" in prohibited
        assert "Output/research/" in prohibited
        assert "Output/system_learning/" in prohibited

    def test_authorized_runtime_chain(self):
        """Constitution must declare authorized runtime chain outputs."""
        har = self.CONST.get("hard_authority_rule", {})
        chain = har.get("authorized_runtime_chain", [])
        assert len(chain) > 0, "authorized_runtime_chain is empty"
        assert "Output/current/" in chain
        # Gate outputs must be covered
        assert "Output/k_measurement/" in chain, "k_measurement gate output not in authorized chain"
        assert "Output/x_measurement/" in chain, "x_measurement gate output not in authorized chain"
        assert "Output/caselab/" in chain, "caselab output not in authorized chain"

    def test_bridge_rule_declared(self):
        """Constitution must declare how sandbox reaches core."""
        har = self.CONST.get("hard_authority_rule", {})
        assert "bridge_rule" in har, "Missing bridge_rule — how does sandbox reach core?"


# ── Code-Level Governance Invariants ─────────────────────────────────────

class TestCodeGovernance:
    """Tests that enforce governance rules at the code level, not just YAML."""

    def test_framework_output_single_writer(self):
        """Only bridge_replay_to_current.py may write Output/current/framework_output.json.

        All other scripts must read it, not write it. This prevents
        multiple writers from producing conflicting core artifacts.
        Includes Workbench submodule scan.
        """
        canonical_writer = "bridge_replay_to_current.py"
        violations = []
        write_indicators = ("write_text", "write(", "dump", "json.dump")

        # Scan scripts/ and Workbench/src/
        scan_dirs = [
            ROOT / "scripts",
            ROOT / "Workbench" / "src" / "workbench",
        ]

        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for py_file in scan_dir.rglob("*.py"):
                if py_file.name == canonical_writer:
                    continue
                if py_file.name.startswith("_"):
                    continue
                source = py_file.read_text(encoding="utf-8")
                if "framework_output" not in source:
                    continue
                for line in source.splitlines():
                    if "framework_output" in line and any(
                        w in line.lower() for w in write_indicators
                    ):
                        if "current" in line or "CURRENT" in line:
                            rel = py_file.relative_to(ROOT)
                            violations.append(
                                f"{rel}: writes framework_output to current — "
                                f"only {canonical_writer} is authorized"
                            )
                            break

        assert not violations, (
            "Non-canonical framework_output writers:\n" + "\n".join(violations)
        )

    def test_root_scripts_budget(self):
        """Root scripts must not exceed 72. One-in-one-out rule."""
        scripts_dir = ROOT / "scripts"
        root_scripts = [
            f for f in scripts_dir.glob("*.py")
            if not f.name.startswith("_") and f.name != "__init__.py"
        ]
        assert len(root_scripts) <= 72, (
            f"Root scripts count {len(root_scripts)} exceeds budget of 72. "
            f"Archive or module-absorb a script before adding new ones."
        )
