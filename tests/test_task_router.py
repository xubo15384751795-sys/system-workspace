from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = ROOT / "Workbench" / "agent_harness" / "structural-research-harness"

if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from tools.task_router import route_task  # noqa: E402


def test_route_task_selects_harvester_for_fuzzy_data_source_request() -> None:
    decision = route_task("优化数据源采集的新鲜度和溯源检查，验证通过但不要发布 release")

    assert decision["primary_module"] == "Harvester"
    assert decision["context_file"] == "module_contexts/harvester.md"
    assert decision["recommended_mode"] == "verify"
    assert decision["requires_routing_decision_record"] is True
    assert "module_contexts/harvester.md" in decision["read_first"]
    assert any(expert["id"] == "datahub_implementation" for expert in decision["activated_experts"])


def test_route_task_escalates_claim_and_paper_work() -> None:
    decision = route_task("Calibrate paper claims about Sigma_t benchmark outperformance")

    assert decision["primary_module"] == "Deformation Framework"
    assert decision["requires_routing_decision_record"] is True
    expert_ids = {expert["id"] for expert in decision["activated_experts"]}
    assert "claim_guardian" in expert_ids
    assert "paper_claim_calibration" in expert_ids
    assert "referee_benchmark_dominance" in expert_ids


def test_route_task_tool_is_available_through_system_cli() -> None:
    proc = subprocess.run(
        [
            "python3",
            str(HARNESS_ROOT / "entrypoints" / "system.py"),
            "tools",
            "run",
            "routing.route_task",
            "task=Add a dashboard evidence view for Output/current",
            "--mode",
            "explore",
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    decision = payload["evidence"]["routing_decision"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "routing.route_task"
    assert decision["primary_module"] == "Workbench"
    assert decision["context_file"] == "module_contexts/workbench.md"


def test_system_tools_list_includes_routing_and_deformation_tools() -> None:
    proc = subprocess.run(
        [
            "python3",
            str(HARNESS_ROOT / "entrypoints" / "system.py"),
            "tools",
            "list",
            "--mode",
            "explore",
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    tool_ids = {tool["id"] for tool in payload["tools"]}

    assert "routing.route_task" in tool_ids
    assert "deformation.list_snapshots" in tool_ids
