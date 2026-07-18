"""Claim Ladder Tracker — tests for cross-run claim progression.

Verifies that claim ladder tracker correctly evaluates M/D persistence,
CaseLab improvement, HMM conflict, and invalidation across runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.commands.weekly.claim_ladder_tracker import (
    _check_rule,
    _evaluate_policy_rules,
    apply_transitions,
    check_caselab_improvement,
    check_hmm_conflict,
    check_invalidation,
    check_md_persistence,
    evaluate_progression,
    find_previous_claim_run_dir,
    find_previous_run_dir,
    load_previous_pending,
    load_state,
    save_state,
)


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    """Redirect I/O to temp directory."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    output_dir = tmp_path / "claim_ladder"
    caselab_dir = tmp_path / "caselab"
    caselab_dir.mkdir(parents=True, exist_ok=True)
    hmm_dir = tmp_path / "ml_signals" / "latest"
    hmm_dir.mkdir(parents=True)
    judgment_dir = tmp_path / "judgment"
    judgment_dir.mkdir()

    monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.RUNS_DIR", runs_dir)
    monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.OUTPUT_DIR", output_dir)
    monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.CASELAB_DIR", caselab_dir)
    monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.HMM_PATH", hmm_dir / "regime_hmm.json")
    monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.JUDGMENT_PATH", judgment_dir / "latest.json")
    return runs_dir, output_dir, caselab_dir, hmm_dir, judgment_dir


def _make_run(runs_dir: Path, run_id: str, status: str = "success", pending_items=None):
    """Create a mock run bundle."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"status": status}))
    if pending_items is not None:
        (run_dir / "feedback_pending.json").write_text(json.dumps(pending_items))
    return run_dir


def _make_claim_item(hypothesis="stress_relief in M/D", tier=1, gap=0.12):
    return {
        "item": f"Claim ladder: tier={tier} — {hypothesis}",
        "source": "claim_ladder",
        "validation_type": "claim_verification",
        "priority": "high",
        "metadata": {
            "claim_tier": tier,
            "claim_label": "mechanism_hypothesis",
            "mechanism_hypothesis": hypothesis,
            "watch_conditions": ["M persists"],
            "invalidation_conditions": ["M reverses sign"],
            "caselab_score_gap": gap,
            "md_persistence_requirement": "persisted >= 2 runs",
        },
    }


def _make_judgment(meaning=None, gate_status=None):
    return {
        "decision": "WATCH_ONLY",
        "meaning": meaning or ["M=-2.09 stress building, D=-0.76"],
        "claim_ladder": {"tier": 1, "label": "mechanism_hypothesis"},
        "gate_status": gate_status or {},
    }


# ── find_previous_run_dir ───────────────────────────────────────────────────

def test_find_previous_run_dir(_isolated_dirs):
    runs_dir = _isolated_dirs[0]
    _make_run(runs_dir, "run_1", "success")
    _make_run(runs_dir, "run_2", "running")  # not complete
    found = find_previous_run_dir()
    assert found is not None
    assert found.name == "run_1"


def test_find_previous_run_dir_none(_isolated_dirs):
    assert find_previous_run_dir() is None


def test_find_previous_claim_run_dir_skips_generic_feedback(_isolated_dirs):
    runs_dir = _isolated_dirs[0]
    _make_run(
        runs_dir,
        "run_1",
        "success",
        pending_items=[_make_claim_item("stress_relief hypothesis")],
    )
    _make_run(
        runs_dir,
        "run_2",
        "success",
        pending_items=[{"source": "judgment_layer", "item": "Low confidence"}],
    )
    found = find_previous_claim_run_dir()
    assert found is not None
    assert found.name == "run_1"


# ── check_md_persistence ────────────────────────────────────────────────────

def test_md_persistence_confirmed(_isolated_dirs):
    item = _make_claim_item("stress_relief in M/D values")
    judgment = _make_judgment(meaning=["M shows stress relief pattern"])
    result = check_md_persistence(item, judgment)
    assert result["persisted"] is True
    assert result["status"] == "confirmed"


def test_md_persistence_reversed(_isolated_dirs):
    item = _make_claim_item("stress_relief in M/D values")
    judgment = _make_judgment(meaning=["M shows stress building pattern"])
    result = check_md_persistence(item, judgment)
    assert result["persisted"] is False
    assert result["status"] == "reversed"


# ── check_caselab_improvement ───────────────────────────────────────────────

def test_caselab_improvement_no_data(_isolated_dirs):
    item = _make_claim_item(gap=0.15)
    result = check_caselab_improvement(item)
    # No CaseLab file → gap unchanged → stable
    assert result["status"] == "stable"


def test_caselab_improvement_with_data(_isolated_dirs, tmp_path, monkeypatch):
    caselab_dir = _isolated_dirs[2]
    caselab_dir.mkdir(parents=True, exist_ok=True)
    import datetime as _dt
    today = _dt.date.today().isoformat()
    caselab = {"match_quality": {"top_score": 0.50, "thresholds": {"usable": 0.55}}}
    (caselab_dir / f"{today}.json").write_text(json.dumps(caselab))

    item = _make_claim_item(gap=0.15)  # previous gap was 0.15
    result = check_caselab_improvement(item)
    assert result["current_gap"] == pytest.approx(0.05)
    assert result["improved"] is True
    assert result["status"] == "improved"


# ── check_hmm_conflict ─────────────────────────────────────────────────────

def test_hmm_conflict_no_data(_isolated_dirs):
    item = _make_claim_item("stress_relief")
    result = check_hmm_conflict(item)
    assert result["status"] == "no_data"


def test_hmm_conflict_detected(_isolated_dirs):
    hmm_dir = _isolated_dirs[3]
    (hmm_dir / "regime_hmm.json").write_text(json.dumps({"regime": "volatile"}))

    item = _make_claim_item("stress_relief hypothesis")
    result = check_hmm_conflict(item)
    assert result["conflict"] is True
    assert result["status"] == "conflict"


def test_hmm_aligned(_isolated_dirs):
    hmm_dir = _isolated_dirs[3]
    (hmm_dir / "regime_hmm.json").write_text(json.dumps({"regime": "volatile"}))

    item = _make_claim_item("stress_building hypothesis")
    result = check_hmm_conflict(item)
    assert result["conflict"] is False
    assert result["status"] == "aligned"


def test_hmm_dict_regime_supported(_isolated_dirs):
    hmm_dir = _isolated_dirs[3]
    (hmm_dir / "regime_hmm.json").write_text(json.dumps({"regime": {"current": "volatile"}}))

    item = _make_claim_item("stress_relief hypothesis")
    result = check_hmm_conflict(item)
    assert result["current_regime"] == "volatile"
    assert result["status"] == "conflict"


# ── check_invalidation ──────────────────────────────────────────────────────

def test_invalidation_no_conditions(_isolated_dirs):
    item = {"metadata": {"invalidation_conditions": []}}
    judgment = _make_judgment()
    result = check_invalidation(item, judgment)
    assert result["status"] == "no_conditions"


def test_invalidation_triggered_hmm(_isolated_dirs):
    item = _make_claim_item()
    item["metadata"]["invalidation_conditions"] = ["HMM stability degrades"]
    judgment = _make_judgment(gate_status={"hmm_stability": "WEAK"})
    result = check_invalidation(item, judgment)
    assert len(result["triggered"]) == 1
    assert result["status"] == "triggered"


def test_invalidation_not_triggered(_isolated_dirs):
    item = _make_claim_item()
    judgment = _make_judgment(gate_status={"hmm_stability": "ADEQUATE"})
    result = check_invalidation(item, judgment)
    assert len(result["triggered"]) == 0
    assert result["status"] == "not_triggered"


# ── evaluate_progression ────────────────────────────────────────────────────

def test_evaluate_progression_tracking(_isolated_dirs):
    items = [_make_claim_item("stress_relief hypothesis")]
    judgment = _make_judgment(meaning=["M shows stress relief pattern"])
    results = evaluate_progression(items, judgment)
    assert len(results) == 1
    assert results[0]["overall_status"] in ("tracking", "progressing")


def test_evaluate_progression_invalidated(_isolated_dirs):
    hmm_dir = _isolated_dirs[3]
    (hmm_dir / "regime_hmm.json").write_text(json.dumps({"regime": "stress"}))

    items = [_make_claim_item("stress_building hypothesis")]
    items[0]["metadata"]["invalidation_conditions"] = ["M reverses sign"]
    judgment = _make_judgment(
        meaning=["M shows stress relief pattern"],
        gate_status={"hmm_stability": "WEAK"},
    )
    results = evaluate_progression(items, judgment)
    assert len(results) == 1
    # Should be invalidated or reversed
    assert results[0]["overall_status"] in ("invalidated", "reversed")


def test_evaluate_progression_empty(_isolated_dirs):
    results = evaluate_progression([], _make_judgment())
    assert results == []


# ── load_previous_pending ──────────────────────────────────────────────────

def test_load_previous_pending(_isolated_dirs):
    runs_dir = _isolated_dirs[0]
    items = [_make_claim_item()]
    run_dir = _make_run(runs_dir, "test_run", pending_items=items)
    loaded = load_previous_pending(run_dir)
    assert len(loaded) == 1
    assert loaded[0]["source"] == "claim_ladder"


def test_load_previous_pending_missing(_isolated_dirs):
    runs_dir = _isolated_dirs[0]
    run_dir = runs_dir / "empty_run"
    run_dir.mkdir()
    loaded = load_previous_pending(run_dir)
    assert loaded == []


# ── _check_rule ─────────────────────────────────────────────────────────────

class TestCheckRule:
    """Tests for the policy rule evaluation engine."""

    def test_ge_comparison_float(self):
        evidence = {"caselab_top_score": 0.45}
        assert _check_rule("caselab_top_score >= 0.30", evidence) is True
        assert _check_rule("caselab_top_score >= 0.50", evidence) is False

    def test_le_comparison_float(self):
        evidence = {"replay_false_positive_rate": 0.35}
        assert _check_rule("replay_false_positive_rate <= 0.40", evidence) is True
        assert _check_rule("replay_false_positive_rate <= 0.30", evidence) is False

    def test_eq_comparison_bool(self):
        evidence = {"hmm_conflict": False}
        assert _check_rule("hmm_conflict == false", evidence) is True
        assert _check_rule("hmm_conflict == true", evidence) is False

    def test_ne_comparison(self):
        evidence = {"md_direction": "up"}
        assert _check_rule("md_direction != down", evidence) is True

    def test_gt_lt_comparison_int(self):
        evidence = {"active_mechanism_count": 2}
        assert _check_rule("active_mechanism_count > 1", evidence) is True
        assert _check_rule("active_mechanism_count < 3", evidence) is True

    def test_or_compound_rule(self):
        evidence = {"active_mechanism_count": 0, "caselab_top_score": 0.45}
        assert _check_rule("active_mechanism_count >= 1 OR caselab_top_score >= 0.30", evidence) is True

    def test_or_compound_rule_both_false(self):
        evidence = {"active_mechanism_count": 0, "caselab_top_score": 0.10}
        assert _check_rule("active_mechanism_count >= 1 OR caselab_top_score >= 0.30", evidence) is False

    def test_and_compound_rule(self):
        evidence = {"active_mechanism_count": 0, "caselab_top_score": 0.25}
        assert _check_rule("active_mechanism_count == 0 AND caselab_top_score < 0.30", evidence) is True

    def test_and_compound_rule_one_false(self):
        evidence = {"active_mechanism_count": 1, "caselab_top_score": 0.25}
        assert _check_rule("active_mechanism_count == 0 AND caselab_top_score < 0.30", evidence) is False

    def test_missing_evidence_returns_false(self):
        evidence = {}
        assert _check_rule("caselab_top_score >= 0.30", evidence) is False

    def test_bare_boolean_variable(self):
        evidence = {"some_flag": True}
        assert _check_rule("some_flag", evidence) is True
        evidence["some_flag"] = False
        assert _check_rule("some_flag", evidence) is False

    def test_special_any_tier2_trigger(self):
        evidence = {}
        assert _check_rule("any tier 2 demotion trigger", evidence) is False

    def test_unparseable_rule_returns_false(self):
        evidence = {}
        assert _check_rule("not_a_real_rule", evidence) is False


# ── _evaluate_policy_rules ──────────────────────────────────────────────────

class TestEvaluatePolicyRules:
    """Tests for promotion/demotion policy evaluation."""

    @pytest.fixture
    def policy(self):
        return {
            "tiers": {
                0: {
                    "label": "diagnostic_claim",
                    "demotion_triggers": [],
                },
                1: {
                    "label": "mechanism_hypothesis",
                    "promotion_requirements": [
                        {"id": "caselab_score", "rule": "caselab_top_score >= 0.30", "description": "CaseLab threshold"},
                    ],
                    "demotion_triggers": [
                        {"id": "low_score", "rule": "caselab_top_score < 0.10", "severity": "immediate", "description": "Score too low"},
                    ],
                },
                2: {
                    "label": "watch_condition",
                    "promotion_requirements": [
                        {"id": "md_persist", "rule": "md_direction_consecutive_runs >= 2", "description": "Direction persistence"},
                        {"id": "no_conflict", "rule": "hmm_conflict == false", "description": "No HMM conflict"},
                    ],
                    "demotion_triggers": [],
                },
            }
        }

    def test_promotion_eligible(self, policy):
        claim = {"current_tier": 0}
        evidence = {"caselab_top_score": 0.40}
        eligible, blockers, triggers = _evaluate_policy_rules(claim, evidence, policy)
        assert eligible is True
        assert blockers == []
        assert triggers == []

    def test_promotion_blocked(self, policy):
        claim = {"current_tier": 0}
        evidence = {"caselab_top_score": 0.20}
        eligible, blockers, triggers = _evaluate_policy_rules(claim, evidence, policy)
        assert eligible is False
        assert len(blockers) == 1
        assert blockers[0]["id"] == "caselab_score"

    def test_demotion_triggered(self, policy):
        claim = {"current_tier": 1}
        evidence = {"caselab_top_score": 0.05}
        eligible, blockers, triggers = _evaluate_policy_rules(claim, evidence, policy)
        assert len(triggers) == 1
        assert triggers[0]["id"] == "low_score"

    def test_max_tier_returns_blocker(self, policy):
        claim = {"current_tier": 2}
        evidence = {}
        eligible, blockers, triggers = _evaluate_policy_rules(claim, evidence, policy)
        assert eligible is False
        assert any(b["id"] == "max_tier" for b in blockers)

    def test_multiple_promotion_requirements(self, policy):
        claim = {"current_tier": 1}
        # Both requirements met
        evidence = {"md_direction_consecutive_runs": 3, "hmm_conflict": False}
        eligible, blockers, triggers = _evaluate_policy_rules(claim, evidence, policy)
        assert eligible is True
        assert blockers == []

    def test_partial_promotion_requirements(self, policy):
        claim = {"current_tier": 1}
        # Only one requirement met
        evidence = {"md_direction_consecutive_runs": 3, "hmm_conflict": True}
        eligible, blockers, triggers = _evaluate_policy_rules(claim, evidence, policy)
        assert eligible is False
        assert len(blockers) == 1


# ── apply_transitions ────────────────────────────────────────────────────────

class TestApplyTransitions:
    """Tests for the state transition engine."""

    @pytest.fixture
    def policy(self):
        return {
            "tiers": {
                0: {"label": "diagnostic_claim", "demotion_triggers": []},
                1: {
                    "label": "mechanism_hypothesis",
                    "promotion_requirements": [
                        {"id": "score", "rule": "caselab_top_score >= 0.30", "description": "Score threshold"},
                    ],
                    "demotion_triggers": [
                        {"id": "low", "rule": "caselab_top_score < 0.10", "severity": "immediate", "description": "Too low"},
                    ],
                },
                2: {
                    "label": "watch_condition",
                    "promotion_requirements": [],
                    "demotion_triggers": [],
                },
                3: {
                    "label": "operational_research",
                    "promotion_requirements": [],
                    "demotion_triggers": [],
                },
            }
        }

    def test_new_claim_created(self, policy):
        state = {"schema_version": "claim_ladder_state.v1", "claims": []}
        progression = [{
            "previous_run_claim": {"claim_tier": 0, "claim_label": "diagnostic_claim", "mechanism_hypothesis": "test hypothesis"},
            "checks": {
                "caselab_improvement": {"current_gap": 0.20, "status": "stable"},
                "md_persistence": {"persisted": False, "current_direction": "unknown", "status": "unknown"},
                "hmm_conflict": {"conflict": False, "status": "no_data"},
                "invalidation": {"triggered": [], "conditions_checked": 0},
            },
            "overall_status": "tracking",
        }]
        result = apply_transitions(state, progression, policy)
        assert len(result["claims"]) == 1
        assert result["claims"][0]["mechanism_hypothesis"] == "test hypothesis"

    def test_promotion_applied(self, policy):
        state = {"schema_version": "claim_ladder_state.v1", "claims": []}
        progression = [{
            "previous_run_claim": {"claim_tier": 0, "claim_label": "diagnostic_claim", "mechanism_hypothesis": "promotable"},
            "checks": {
                "caselab_improvement": {"current_gap": 0.10, "status": "improved"},
                "md_persistence": {"persisted": True, "current_direction": "up", "status": "confirmed"},
                "hmm_conflict": {"conflict": False, "status": "aligned"},
                "invalidation": {"triggered": [], "conditions_checked": 1},
            },
            "overall_status": "progressing",
        }]
        result = apply_transitions(state, progression, policy)
        claim = result["claims"][0]
        assert claim["current_tier"] == 1
        assert claim["status"] == "promoted"
        assert result["summary"]["promotions_this_run"] == 1

    def test_invalidation_applied(self, policy):
        state = {"schema_version": "claim_ladder_state.v1", "claims": []}
        progression = [{
            "previous_run_claim": {"claim_tier": 1, "claim_label": "mechanism_hypothesis", "mechanism_hypothesis": "doomed"},
            "checks": {
                "caselab_improvement": {"current_gap": 0.20, "status": "stable"},
                "md_persistence": {"persisted": False, "current_direction": "down", "status": "reversed"},
                "hmm_conflict": {"conflict": True, "status": "conflict"},
                "invalidation": {"triggered": ["M reverses sign"], "conditions_checked": 1},
            },
            "overall_status": "invalidated",
        }]
        result = apply_transitions(state, progression, policy)
        claim = result["claims"][0]
        assert claim["current_tier"] == 0
        assert claim["status"] == "invalidated"
        assert result["summary"]["demotions_this_run"] == 1

    def test_existing_claim_accumulates_and_promotes(self, policy):
        """Existing claim at tier 1 with strong evidence should get promoted to tier 2."""
        state = {
            "schema_version": "claim_ladder_state.v1",
            "claims": [{
                "claim_id": "claim-test",
                "current_tier": 1,
                "tier_label": "mechanism_hypothesis",
                "mechanism_hypothesis": "existing",
                "status": "active",
                "entered_tier_at": "2026-06-17T00:00:00",
                "runs_at_current_tier": 3,
                "evidence": {"md_direction_consecutive_runs": 2},
                "history": [],
            }],
        }
        progression = [{
            "previous_run_claim": {"claim_tier": 1, "claim_label": "mechanism_hypothesis", "mechanism_hypothesis": "existing"},
            "checks": {
                "caselab_improvement": {"current_gap": 0.20, "status": "stable"},
                "md_persistence": {"persisted": True, "current_direction": "up", "status": "confirmed"},
                "hmm_conflict": {"conflict": False, "status": "aligned"},
                "invalidation": {"triggered": [], "conditions_checked": 0},
            },
            "overall_status": "tracking",
        }]
        result = apply_transitions(state, progression, policy)
        claim = result["claims"][0]
        # md_direction_consecutive_runs accumulates from 2 → 3
        assert claim["evidence"]["md_direction_consecutive_runs"] == 3
        # Strong evidence triggers promotion to tier 2
        assert claim["current_tier"] == 2
        assert claim["status"] == "promoted"
        # Promotion resets runs_at_current_tier
        assert claim["runs_at_current_tier"] == 0

    def test_summary_computed(self, policy):
        state = {"schema_version": "claim_ladder_state.v1", "claims": []}
        result = apply_transitions(state, [], policy)
        assert result["summary"]["total_claims"] == 0
        assert result["summary"]["active_claims"] == 0
        assert result["summary"]["highest_tier"] == 0


# ── load_state / save_state ──────────────────────────────────────────────────

class TestStateIO:
    """Tests for persistent state I/O."""

    def test_load_state_missing_file(self, _isolated_dirs, monkeypatch):
        output_dir = _isolated_dirs[1]
        monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.STATE_PATH", output_dir / "state.json")
        state = load_state()
        assert state["schema_version"] == "claim_ladder_state.v1"
        assert state["claims"] == []

    def test_save_and_load_roundtrip(self, _isolated_dirs, monkeypatch):
        output_dir = _isolated_dirs[1]
        state_path = output_dir / "state.json"
        monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.STATE_PATH", state_path)
        monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.OUTPUT_DIR", output_dir)

        state = {
            "schema_version": "claim_ladder_state.v1",
            "claims": [{"mechanism_hypothesis": "test", "current_tier": 1}],
        }
        save_state(state)
        loaded = load_state()
        assert loaded["claims"][0]["mechanism_hypothesis"] == "test"
        assert loaded["claims"][0]["current_tier"] == 1

    def test_load_state_wrong_schema(self, _isolated_dirs, monkeypatch):
        output_dir = _isolated_dirs[1]
        output_dir.mkdir(parents=True, exist_ok=True)
        state_path = output_dir / "state.json"
        state_path.write_text('{"schema_version": "wrong.v1", "claims": []}')
        monkeypatch.setattr("scripts.commands.weekly.claim_ladder_tracker.STATE_PATH", state_path)
        state = load_state()
        # Should return fresh state since schema version doesn't match
        assert state["schema_version"] == "claim_ladder_state.v1"
        assert state["claims"] == []
