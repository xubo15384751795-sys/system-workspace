from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _minimal_policy() -> dict:
    return {
        "authority_boundary": {"credit_never_grants_authority": True},
        "credit_sources": {
            "registration": {"review_weight": 1, "suggests_review_for": "registered"},
            "provenance": {"review_weight": 2, "suggests_review_for": "registered"},
            "consumed_by_module": {"review_weight": 2, "suggests_review_for": "preferred"},
            "stable_consumption": {"review_weight": 3, "suggests_review_for": "preferred"},
        },
        "demotion_triggers": [
            {"id": "gate_blocked_or_watch", "to": "registered"},
            {"id": "graph_drift_detected", "to": "registered"},
            {"id": "trace_incomplete", "to": "low"},
        ],
    }


def test_credit_score_computes_from_signals() -> None:
    module = _load("incentive_engine", ROOT / "scripts" / "_incentive_engine.py")
    signals = {
        "trace_complete": True,
        "can_enter_current": True,
        "effective_can_affect_core": False,
        "graph_drift_count": 0,
        "total_in_degree": 2,
        "core_capable_completed": 1,
    }
    credit = module.compute_credit_score(signals, _minimal_policy())
    assert credit["total_score"] > 0
    assert "registration" in credit["active_sources"]
    assert credit["suggested_tier"] in {"registered", "preferred"}


def test_demotion_on_gate_blocked() -> None:
    module = _load("incentive_engine", ROOT / "scripts" / "_incentive_engine.py")
    signals = {
        "trace_complete": True,
        "can_enter_current": False,
        "graph_drift_count": 0,
        "graph_invariants_valid": True,
    }
    result = module.resolve_priority_tier(signals, _minimal_policy(), current_tier="preferred")
    assert result["final_tier"] == "registered"
    assert "gate_blocked_or_watch" in result["demotion_reasons"]


def test_submission_scoring_and_gaps() -> None:
    module = _load("incentive_engine", ROOT / "scripts" / "_incentive_engine.py")
    required = ["submission_id", "owner", "retire_after"]
    submission = {
        "submission_id": "probe_001",
        "owner": "System",
        "status": "submitted",
        "current_priority": "preferred",
        "submission_type": "topology_change",
        "evidence_paths": ["Output/sandbox/x.json"],
    }
    scored = module.score_submission(submission, _minimal_policy(), required_fields=required)
    assert scored["credit_bonus"] > 0
    assert scored["topology_change"] is True
    assert "retire_after" in scored["gaps"]
    assert scored["effective_priority"] == "low"


def test_experimental_submission_registry_fixture(tmp_path: Path) -> None:
    module = _load("incentive_engine", ROOT / "scripts" / "_incentive_engine.py")
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "incentive_policy.yaml").write_text(
        (ROOT / "governance/incentive_policy.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "governance" / "experimental_submission_registry.yaml").write_text(
        """
schema_version: experimental_submission.v1
required_fields:
  - submission_id
  - owner
  - retire_after
  - rollback_plan
submissions:
  - submission_id: etf_bridge_001
    submitted_by: Workbench
    owner: Workbench
    status: submitted
    current_priority: low
    submission_type: exploration
    rule_deviation: [did_not_enter_harvester_first]
    affected_paths: [scripts/refresh_etf_panel.py]
    evidence_paths: [Output/sandbox/etf_test.json]
    review_deadline: "2026-07-01"
    reviewer: null
    decision: null
    decision_reason: null
    rollback_plan: revert script
    retire_after: "2026-07-15"
""",
        encoding="utf-8",
    )
    (tmp_path / "Output/system_learning/latest").mkdir(parents=True)
    (tmp_path / "Output/system_learning/latest/governance_status.json").write_text(
        json.dumps({"run_trace": {"trace_complete": True}, "gates": {"can_enter_current": True}}),
        encoding="utf-8",
    )
    (tmp_path / "Output/system_learning/latest/authority_graph.json").write_text(
        json.dumps({"invariants": {"valid": True}, "metrics": {"drift_count": 0}}),
        encoding="utf-8",
    )
    (tmp_path / "governance" / "entrypoint_registry.yaml").write_text("{}", encoding="utf-8")

    import yaml

    policy = yaml.safe_load((tmp_path / "governance/incentive_policy.yaml").read_text(encoding="utf-8"))
    registry = yaml.safe_load(
        (tmp_path / "governance/experimental_submission_registry.yaml").read_text(encoding="utf-8")
    )
    submissions = registry.get("submissions", [])
    assert len(submissions) == 1
    scored = module.score_submission(
        submissions[0],
        policy,
        required_fields=registry.get("required_fields", []),
    )
    assert scored["gaps"] == []
    assert scored["effective_priority"] == "low"


def test_anti_gaming_authority_boundary() -> None:
    module = _load("incentive_engine", ROOT / "scripts" / "_incentive_engine.py")
    bad_policy = {"authority_boundary": {"credit_never_grants_authority": False}}
    report = module.run_anti_gaming_checks(ROOT, bad_policy)
    assert report["valid"] is False
