"""Task router / ToolSpec coverage (hermetic).

In-process routing/planning plus CLI mode/contract checks that do not mutate
operator Data/Output. Live index/refresh/replay/promote live in
test_task_router_operator.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = ROOT / "packages" / "workbench" / "agents" / "harness"
CONTRACTS = ROOT / "packages" / "workbench" / "contracts"
SYSTEM_ENTRY = HARNESS_ROOT / "entrypoints" / "system.py"

if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from tools.coverage_audit import audit_tool_coverage  # noqa: E402
from tools.task_planner import create_task_plan  # noqa: E402
from tools.task_router import route_task  # noqa: E402


def _tools(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SYSTEM_ENTRY), "tools", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def test_route_task_selects_harvester_for_fuzzy_data_source_request() -> None:
    decision = route_task("优化数据源采集的新鲜度和溯源检查，验证通过但不要发布 release")

    assert decision["primary_module"] == "Harvester"
    assert decision["context_file"] == "module_contexts/harvester.md"
    assert decision["recommended_mode"] == "verify"
    assert decision["execution_authority"]["authority_tier"] == "diagnostic"
    assert decision["execution_authority"]["may_dry_run_pipeline_step"] is True
    assert decision["requires_routing_decision_record"] is True
    assert "module_contexts/harvester.md" in decision["read_first"]
    assert any(expert["id"] == "datahub_implementation" for expert in decision["activated_experts"])


def test_resolve_execution_authority_denies_judgment_layer_in_run_mode() -> None:
    from tools.task_router import resolve_execution_authority

    authority = resolve_execution_authority("run", step_id="judgment_layer")
    assert authority["may_execute_pipeline_step"] is False
    assert authority["reasons"]


def test_routing_execute_pipeline_step_dry_run_allowed() -> None:
    proc = _tools(
        "run",
        "routing.execute_pipeline_step",
        "step_id=evidence_grade_report",
        "pipeline_dry_run=true",
        "--mode",
        "run",
        "--json",
    )
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["tool_id"] == "routing.execute_pipeline_step"
    assert payload["evidence"]["execution_authority"]["may_dry_run_pipeline_step"] is True


def test_routing_execute_pipeline_step_blocks_judgment_layer() -> None:
    proc = _tools(
        "run",
        "routing.execute_pipeline_step",
        "step_id=judgment_layer",
        "--mode",
        "run",
        "--json",
        check=False,
    )
    payload = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert payload["ok"] is False
    assert "judgment_layer" in payload["errors"][0]


def test_route_task_escalates_claim_and_paper_work() -> None:
    decision = route_task("Calibrate paper claims about Sigma_t benchmark outperformance")

    assert decision["primary_module"] == "Deformation Framework"
    assert decision["requires_routing_decision_record"] is True
    expert_ids = {expert["id"] for expert in decision["activated_experts"]}
    assert "claim_guardian" in expert_ids
    assert "paper_claim_calibration" in expert_ids
    assert "referee_benchmark_dominance" in expert_ids


def test_route_task_tool_is_available_through_system_cli() -> None:
    proc = _tools(
        "run",
        "routing.route_task",
        "task=Add a dashboard evidence view for Output/current",
        "--mode",
        "explore",
        "--json",
    )
    payload = json.loads(proc.stdout)
    decision = payload["evidence"]["routing_decision"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "routing.route_task"
    assert decision["primary_module"] == "Workbench"
    assert decision["context_file"] == "module_contexts/workbench.md"


def test_system_tools_list_includes_routing_and_deformation_tools() -> None:
    proc = _tools("list", "--mode", "explore", "--json")
    payload = json.loads(proc.stdout)
    tool_ids = {tool["id"] for tool in payload["tools"]}

    assert "routing.route_task" in tool_ids
    assert "routing.create_task_plan" in tool_ids
    assert "routing.tool_coverage_audit" in tool_ids
    assert "deformation.list_snapshots" in tool_ids


def test_create_task_plan_binds_harvester_steps_to_toolspecs() -> None:
    plan = create_task_plan("优化数据源采集的新鲜度和溯源检查，验证通过但不要发布 release")

    assert plan["route"]["primary_module"] == "Harvester"
    assert plan["tool_spec_policy"].startswith("Executable actions must name a ToolSpec")
    assert [step["phase"] for step in plan["steps"]] == [
        "route",
        "explore",
        "verify",
        "governance",
    ]
    bound_tools = {
        tool_id for step in plan["steps"] for tool_id in step["tool_spec"]["tool_ids"]
    }
    assert "routing.route_task" in bound_tools
    assert "harvester.inspect_release" in bound_tools
    assert "harvester.verify_release" in bound_tools
    assert "learning_hub.write_verification_record" in bound_tools
    assert plan["blocked_actions"] == []


def test_create_task_plan_blocks_unregistered_implementation_actions() -> None:
    plan = create_task_plan("Implement a new Workbench dashboard panel for Output/current")

    assert plan["route"]["primary_module"] == "Workbench"
    blocked = plan["blocked_actions"]
    assert blocked
    assert any(step["phase"] == "implement" for step in blocked)
    assert all(step["tool_spec"]["status"] == "missing_tool_spec" for step in blocked)


def test_create_task_plan_tool_is_available_through_system_cli() -> None:
    proc = _tools(
        "run",
        "routing.create_task_plan",
        "task=Implement a new Workbench dashboard panel for Output/current",
        "--mode",
        "explore",
        "--json",
    )
    payload = json.loads(proc.stdout)
    plan = payload["evidence"]["task_plan"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "routing.create_task_plan"
    assert plan["route"]["primary_module"] == "Workbench"
    assert plan["blocked_actions"]


def test_tool_coverage_audit_marks_promotion_covered() -> None:
    audit = audit_tool_coverage()

    assert audit["surface_count"] >= 1
    promote = next(
        item for item in audit["surfaces"] if item["script"] == "scripts/promote_snapshot.py"
    )
    assert promote["priority"] == "critical"
    assert promote["coverage"] == "covered"
    assert "artifact.promote_snapshot" in promote["matched_tool_ids"]


def test_tool_coverage_audit_marks_contract_validation_covered() -> None:
    audit = audit_tool_coverage()

    contract = next(
        item
        for item in audit["surfaces"]
        if item["script"] == "scripts/validate_workbench_contract.py"
    )
    assert contract["priority"] == "high"
    assert contract["coverage"] == "covered"
    assert "protocols.validate_contract" in contract["matched_tool_ids"]


def test_tool_coverage_audit_marks_system_index_covered() -> None:
    audit = audit_tool_coverage()

    system_index = next(
        item for item in audit["surfaces"] if item["script"] == "scripts/build_system_index.py"
    )
    assert system_index["priority"] == "high"
    assert system_index["coverage"] == "covered"
    assert "data_output.build_system_index" in system_index["matched_tool_ids"]


def test_tool_coverage_audit_marks_refresh_current_covered() -> None:
    audit = audit_tool_coverage()

    refresh = next(
        item
        for item in audit["surfaces"]
        if item["script"] == "scripts/refresh_output_current.py"
    )
    assert refresh["priority"] == "high"
    assert refresh["coverage"] == "covered"
    assert "workbench.refresh_current" in refresh["matched_tool_ids"]


def test_tool_coverage_audit_marks_replay_evaluation_covered() -> None:
    audit = audit_tool_coverage()

    replay = next(
        item
        for item in audit["surfaces"]
        if item["script"] == "scripts/structural_replay_evaluation.py"
    )
    assert replay["priority"] == "high"
    assert replay["coverage"] == "covered"
    assert "deformation.evaluate_replay" in replay["matched_tool_ids"]


def test_create_task_plan_binds_protocol_validation_tasks_to_toolspec() -> None:
    plan = create_task_plan("Validate the provider-release contract schema example")

    assert plan["route"]["primary_module"] == "Protocols"
    bound_tools = {
        tool_id for step in plan["steps"] for tool_id in step["tool_spec"]["tool_ids"]
    }
    assert "protocols.validate_contract" in bound_tools
    assert plan["blocked_actions"] == []


def test_create_task_plan_binds_system_index_run_tasks_to_toolspec() -> None:
    plan = create_task_plan("Run Data/system_index refresh")

    assert plan["route"]["primary_module"] == "Data and Output"
    bound_tools = {
        tool_id for step in plan["steps"] for tool_id in step["tool_spec"]["tool_ids"]
    }
    assert "data_output.build_system_index" in bound_tools
    assert plan["blocked_actions"] == []


def test_create_task_plan_binds_refresh_current_tasks_to_toolspec() -> None:
    plan = create_task_plan("Refresh Output/current")

    assert plan["route"]["primary_module"] == "Workbench"
    assert plan["route"]["recommended_mode"] == "run"
    bound_tools = {
        tool_id for step in plan["steps"] for tool_id in step["tool_spec"]["tool_ids"]
    }
    assert "workbench.refresh_current" in bound_tools


def test_create_task_plan_binds_replay_verification_to_toolspec() -> None:
    plan = create_task_plan("Verify structural replay for latest deformation run")

    assert plan["route"]["primary_module"] == "Deformation Framework"
    bound_tools = {
        tool_id for step in plan["steps"] for tool_id in step["tool_spec"]["tool_ids"]
    }
    assert "deformation.evaluate_replay" in bound_tools


def test_create_task_plan_includes_tool_coverage_summary() -> None:
    plan = create_task_plan("Implement a new Workbench dashboard panel for Output/current")

    summary = plan["tool_coverage_summary"]
    assert summary["surface_count"] >= 1
    assert summary["missing_count"] >= 1
    assert "critical" not in summary["missing_by_priority"]
    assert "high" not in summary["missing_by_priority"]
    assert "medium" in summary["missing_by_priority"]


def test_tool_coverage_audit_is_available_through_system_cli() -> None:
    proc = _tools("run", "routing.tool_coverage_audit", "--mode", "explore", "--json")
    payload = json.loads(proc.stdout)
    audit = payload["evidence"]["tool_coverage_audit"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "routing.tool_coverage_audit"
    assert audit["missing_count"] >= 1


def test_validate_contract_tool_is_available_through_system_cli() -> None:
    target = CONTRACTS / "workbench" / "examples" / "minimal_provider_release"
    proc = _tools(
        "run",
        "protocols.validate_contract",
        "contract_type=provider-release",
        f"target_path={target}",
        "--mode",
        "verify",
        "--json",
    )
    payload = json.loads(proc.stdout)
    validation = payload["evidence"]["validation"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "protocols.validate_contract"
    assert validation["contract_type"] == "provider-release"
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_validate_contract_tool_validates_minimal_examples() -> None:
    examples = [
        (
            "provider-release",
            CONTRACTS / "workbench" / "examples" / "minimal_provider_release",
        ),
        (
            "evidence-panel",
            CONTRACTS
            / "workbench"
            / "examples"
            / "minimal_provider_release"
            / "data"
            / "evidence_panel.csv",
        ),
        (
            "model-run",
            CONTRACTS / "workbench" / "examples" / "minimal_framework_run" / "model_run.json",
        ),
        (
            "report-artifacts",
            CONTRACTS
            / "workbench"
            / "examples"
            / "minimal_framework_run"
            / "report_artifacts.json",
        ),
    ]

    for contract_type, target_path in examples:
        proc = _tools(
            "run",
            "protocols.validate_contract",
            f"contract_type={contract_type}",
            f"target_path={target_path}",
            "--mode",
            "verify",
            "--json",
        )
        payload = json.loads(proc.stdout)
        assert payload["ok"] is True
        assert payload["evidence"]["validation"]["valid"] is True


def test_validate_contract_tool_returns_structured_failure_for_bad_path() -> None:
    proc = _tools(
        "run",
        "protocols.validate_contract",
        "contract_type=model-run",
        "target_path=does/not/exist/model_run.json",
        "--mode",
        "verify",
        "--json",
        check=False,
    )
    payload = json.loads(proc.stdout)
    validation = payload["evidence"]["validation"]

    assert proc.returncode == 1
    assert payload["ok"] is False
    assert payload["tool_id"] == "protocols.validate_contract"
    assert validation["contract_type"] == "model-run"
    assert validation["target_path"].replace("\\", "/") == "does/not/exist/model_run.json"
    assert validation["valid"] is False
    assert payload["errors"]


def test_validate_contract_tool_is_verify_or_explore_only() -> None:
    target = (
        CONTRACTS / "workbench" / "examples" / "minimal_framework_run" / "model_run.json"
    )
    proc = _tools(
        "run",
        "protocols.validate_contract",
        "contract_type=model-run",
        f"target_path={target}",
        "--mode",
        "run",
        "--json",
        check=False,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["ok"] is False
    assert "Allowed modes: ['explore', 'verify']" in payload["errors"][0]


def test_build_system_index_dry_run_does_not_write_outputs() -> None:
    output_paths = [
        ROOT / "Data" / "system_index" / "latest.json",
        ROOT / "Data" / "system_index" / "system_catalog.json",
        ROOT / "Data" / "system_index" / "lineage_graph.json",
    ]
    before = {str(path): path.stat().st_mtime_ns if path.exists() else None for path in output_paths}

    proc = _tools(
        "run",
        "data_output.build_system_index",
        "dry_run=true",
        "--mode",
        "run",
        "--json",
    )
    payload = json.loads(proc.stdout)
    after = {str(path): path.stat().st_mtime_ns if path.exists() else None for path in output_paths}

    assert payload["ok"] is True
    assert payload["tool_id"] == "data_output.build_system_index"
    assert before == after


def test_build_system_index_tool_is_run_or_release_only() -> None:
    proc = _tools(
        "run",
        "data_output.build_system_index",
        "--mode",
        "verify",
        "--json",
        check=False,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["ok"] is False
    assert "Allowed modes: ['run', 'release']" in payload["errors"][0]


def test_refresh_current_tool_is_run_or_edit_only() -> None:
    proc = _tools(
        "run",
        "workbench.refresh_current",
        "--mode",
        "verify",
        "--json",
        check=False,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["ok"] is False
    assert "Allowed modes: ['run', 'edit']" in payload["errors"][0]


def test_evaluate_replay_tool_returns_structured_failure_for_bad_run() -> None:
    proc = _tools(
        "run",
        "deformation.evaluate_replay",
        "run_id=missing-run",
        "--mode",
        "verify",
        "--json",
        check=False,
    )
    payload = json.loads(proc.stdout)
    replay = payload["evidence"]["replay_evaluation"]

    assert proc.returncode == 1
    assert payload["ok"] is False
    assert payload["tool_id"] == "deformation.evaluate_replay"
    assert replay["verdict"] == "FAIL"
    assert replay["errors"] == ["deformation run not found: missing-run"]


def test_evaluate_replay_tool_is_explore_or_verify_only() -> None:
    proc = _tools(
        "run",
        "deformation.evaluate_replay",
        "run_id=missing-run",
        "--mode",
        "run",
        "--json",
        check=False,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert payload["ok"] is False
    assert "Allowed modes: ['explore', 'verify']" in payload["errors"][0]
