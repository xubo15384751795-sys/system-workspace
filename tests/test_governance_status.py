from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "governance_status.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("governance_status", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _minimal_root(tmp_path: Path) -> Path:
    run_id = "work_cycle_quick_20260618_000000_test"
    _write_text(tmp_path / "Output/current/latest_run_id.txt", run_id + "\n")
    run_dir = tmp_path / "Output/runs" / run_id
    _write_json(
        run_dir / "manifest.json",
        {
            "run_id": run_id,
            "mode": "work_cycle_quick",
            "status": "OK",
            "steps_count": 6,
            "steps_failed": 0,
        },
    )
    _write_json(run_dir / "input_snapshot.json", {})
    _write_text(run_dir / "steps.jsonl", '{"step": "governance_status", "status": "success"}\n')
    _write_json(run_dir / "artifact_index.json", [])
    _write_json(run_dir / "decision_trace.json", [{"data": {"decision": "WATCH"}}])

    _write_json(
        tmp_path / "Output/judgment/promotion_gate.json",
        {
            "overall_status": "WATCH",
            "claim_ceiling": "mechanism_hypothesis",
            "blocked_gates": [],
            "watch_gates": ["claim_ceiling"],
            "watch_reasons": ["Claim ceiling is mechanism_hypothesis"],
            "allowed_language": ["diagnostic", "watch"],
            "forbidden_language": ["prediction", "signal"],
        },
    )
    _write_json(
        tmp_path / "Output/trade_decision/risk_gate.json",
        {
            "risk_check": {"status": "APPROVED_FOR_RESEARCH"},
            "allowed_actions": {"live_execution": False, "paper_trading": True},
        },
    )
    _write_json(
        tmp_path / "Output/system_learning/latest/supervisor_check.json",
        {"overall_status": "PASS", "review_queue": []},
    )
    _write_json(
        tmp_path / "Output/system_learning/latest/architecture_reality_audit.json",
        {"summary": {"overall_status": "PASS", "total_findings": 0}},
    )
    _write_json(
        tmp_path / "Output/system_learning/latest/output_routing_report.json",
        {"summary": {"overall_status": "CLEAN", "total_findings": 0}},
    )
    _write_text(
        tmp_path / "governance/incentive_policy.yaml",
        """
schema_version: incentive_policy.v1
priority_levels:
  low:
    meaning: Allowed to exist
    can_enter_current: false
    can_affect_core_judgment: false
  registered:
    meaning: Traceable but not current
    can_enter_current: false
    can_affect_core_judgment: false
  preferred:
    meaning: Can enter current
    can_enter_current: true
    can_affect_core_judgment: false
  canonical:
    meaning: Can affect core
    can_enter_current: true
    can_affect_core_judgment: true
""",
    )
    _write_text(
        tmp_path / "governance/experimental_submission_registry.yaml",
        """
schema_version: experimental_submission.v1
submissions: []
review_schedule:
  max_open_age_days: 14
""",
    )
    # Authority graph dependencies
    _write_text(
        tmp_path / "governance/authority_graph_policy.yaml",
        """
bridge_nodes:
  - bridge
surface_path_prefixes:
  - Output/current/
core_judgment_prefixes:
  - Output/judgment/
  - Output/trade_decision/
""",
    )
    _write_text(
        tmp_path / "governance/output_routing_policy.yaml",
        "routes: []\n",
    )
    _write_text(
        tmp_path / "governance/daily_pipeline_registry.yaml",
        "schema_version: daily_pipeline_registry.v2\nsteps: {}\n",
    )
    _write_text(
        tmp_path / "governance/system_constitution.yaml",
        """
schema_version: system_constitution.v1
hard_authority_rule:
  only_current_or_formal_runs_can_affect_core_judgment: true
  authorized_runtime_chain:
    - Output/current/
    - Output/judgment/
""",
    )
    return tmp_path


def test_governance_status_reports_watch_tier(tmp_path: Path) -> None:
    module = _load_module()
    root = _minimal_root(tmp_path)

    report = module.run_governance_status(root)

    assert report["overall_status"] == "WATCH"
    assert report["run_trace"]["trace_complete"] is True
    assert report["gates"]["can_enter_current"] is True
    assert report["gates"]["can_affect_core_judgment"] is False
    assert report["incentive"]["review_status"] == "preferred"


def test_governance_status_surfaces_overdue_exceptions(tmp_path: Path) -> None:
    module = _load_module()
    root = _minimal_root(tmp_path)
    _write_text(
        root / "governance/experimental_submission_registry.yaml",
        """
schema_version: experimental_submission.v1
submissions:
  - submission_id: direct_data_probe
    date: "2026-01-01"
    status: submitted
    current_priority: low
review_schedule:
  max_open_age_days: 14
""",
    )

    report = module.run_governance_status(root)

    assert report["exceptions"]["open_count"] == 1
    assert report["exceptions"]["overdue_count"] == 1
    assert any(item["source"] == "experimental_submission" for item in report["review_queue"])


def test_governance_status_writes_outputs(tmp_path: Path) -> None:
    module = _load_module()
    root = _minimal_root(tmp_path)
    report = module.run_governance_status(root)

    paths = module.write_outputs(report, root)

    assert paths["json"] == "Output/system_learning/latest/governance_status.json"
    assert paths["markdown"] == "Output/system_learning/latest/governance_status.md"
    assert (root / paths["json"]).exists()
    assert "Governance Status" in (root / paths["markdown"]).read_text(encoding="utf-8")
