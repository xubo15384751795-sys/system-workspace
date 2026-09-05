"""task_planner — convert routing decisions into executable checklists.

The planner is deliberately tool-first: every step either names a registered
ToolSpec candidate or marks the work as blocked until a ToolSpec exists. This
keeps the agent from treating scripts and ad-hoc shell commands as invisible
runtime capabilities.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from tools.coverage_audit import audit_tool_coverage
from tools.task_router import route_task


MODULE_TOOL_CANDIDATES: dict[str, dict[str, list[str]]] = {
    "Workbench": {
        "explore": [],
        "implement": [],
        "verify": ["protocols.validate_contract"],
        "run": ["workbench.refresh_current", "workbench.run_pipeline_step"],
        "edit": ["workbench.refresh_current", "workbench.run_pipeline_step"],
    },
    "Deformation v1 Evidence Archive": {
        "explore": ["deformation.list_snapshots", "deformation.inspect_snapshot"],
        "verify": ["deformation.inspect_snapshot", "deformation.evaluate_replay"],
        "implement": [],
    },
    "Harvester": {
        "explore": ["harvester.list_releases", "harvester.inspect_release"],
        "verify": ["harvester.verify_release", "harvester.diff_releases"],
        "implement": [],
        "fetch": [],
    },
    "Protocols": {
        "explore": ["protocols.validate_contract"],
        "verify": ["protocols.validate_contract"],
        "implement": [],
    },
    "Data and Output": {
        "explore": ["deformation.list_snapshots", "harvester.list_releases"],
        "verify": ["deformation.inspect_snapshot", "harvester.verify_release"],
        "implement": [],
        "run": ["data_output.build_system_index"],
        "release": ["artifact.promote_snapshot_preflight", "artifact.promote_snapshot"],
    },
    "Learning Hub": {
        "explore": ["learning_hub.inspect_queue", "learning_hub.query_recurrence"],
        "verify": ["learning_hub.write_verification_record"],
        "implement": [],
    },
    "Agent Routing": {
        "explore": ["routing.route_task", "routing.create_task_plan"],
        "verify": ["routing.create_task_plan", "routing.execute_pipeline_step"],
        "run": ["routing.execute_pipeline_step"],
        "implement": [],
    },
}


RISK_BY_MODE = {
    "explore": "read_only",
    "plan": "read_only",
    "verify": "read_only",
    "implement": "code_edit",
    "fetch": "data_mutation",
    "run": "data_mutation",
    "edit": "code_edit",
    "release": "release_finalization",
}


def _task_id(task: str) -> str:
    digest = hashlib.sha1(task.encode("utf-8")).hexdigest()[:10]
    return f"task-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{digest}"


def _tool_status(tool_ids: list[str], mode: str) -> dict[str, Any]:
    if tool_ids:
        return {
            "status": "bound",
            "tool_ids": tool_ids,
            "missing_reason": "",
        }
    return {
        "status": "missing_tool_spec",
        "tool_ids": [],
        "missing_reason": (
            f"No governed ToolSpec is registered for this {mode} action yet; "
            "do not execute it through an ad-hoc script until one exists."
        ),
    }


def _step(
    *,
    order: int,
    phase: str,
    owner: str,
    content: str,
    mode: str,
    tool_ids: list[str],
    verification: str,
    artifacts: list[str] | None = None,
    gates: list[str] | None = None,
    risk_category: str | None = None,
) -> dict[str, Any]:
    return {
        "order": order,
        "phase": phase,
        "owner_module": owner,
        "content": content,
        "mode": mode,
        "risk_category": risk_category or RISK_BY_MODE.get(mode, "read_only"),
        "tool_spec": _tool_status(tool_ids, mode),
        "artifacts": artifacts or [],
        "verification": verification,
        "gates": gates or [],
        "status": "pending",
    }


def _module_tools(module: str, phase: str) -> list[str]:
    return MODULE_TOOL_CANDIDATES.get(module, {}).get(phase, [])


def create_task_plan(task: str, artifacts: list[str] | None = None) -> dict[str, Any]:
    """Create a structured plan from a fuzzy request."""
    artifacts = artifacts or []
    route = route_task(task, artifacts)
    owner = route["primary_module"]
    recommended_mode = route["recommended_mode"]

    steps: list[dict[str, Any]] = []
    steps.append(
        _step(
            order=1,
            phase="route",
            owner="Agent Routing",
            content="Resolve owning module, context file, experts, and mode",
            mode="explore",
            tool_ids=["routing.route_task"],
            artifacts=[route["context_file"]],
            verification="The task-local context is selected before reading source boundaries",
        )
    )

    steps.append(
        _step(
            order=2,
            phase="explore",
            owner=owner,
            content=f"Inspect current state for {owner}",
            mode="explore",
            tool_ids=_module_tools(owner, "explore"),
            artifacts=route["primary_paths"],
            verification="Current owner artifacts or available state are observed",
        )
    )

    if recommended_mode in {"implement", "fetch", "run", "edit", "release"}:
        steps.append(
            _step(
                order=len(steps) + 1,
                phase="implement" if recommended_mode != "release" else "release",
                owner=owner,
                content=f"Perform the scoped {recommended_mode} action inside {owner}",
                mode=recommended_mode,
                tool_ids=_module_tools(owner, recommended_mode),
                artifacts=artifacts,
                verification="No mutation proceeds unless the step has a governed ToolSpec",
                gates=[
                    "Implementation and verification must be separate phases",
                    "Do not publish or promote from implement mode",
                ],
            )
        )

    steps.append(
        _step(
            order=len(steps) + 1,
            phase="verify",
            owner=owner,
            content=f"Verify outputs and boundary assumptions for {owner}",
            mode="verify",
            tool_ids=_module_tools(owner, "verify"),
            artifacts=artifacts,
            verification="Verifier observes command/tool evidence before any PASS",
            gates=["Verification cannot be performed by the same implement phase"],
        )
    )

    if route["requires_routing_decision_record"]:
        steps.append(
            _step(
                order=len(steps) + 1,
                phase="governance",
                owner="Learning Hub",
                content="Record routing decision, residual risks, and unresolved gates",
                mode="verify",
                tool_ids=["learning_hub.write_verification_record"],
                artifacts=["Output/system_learning/routing_decisions/"],
                verification="Routing decision record or verification record is written",
                gates=["Do not promote exploratory work without owner verification"],
                risk_category="data_mutation",
            )
        )

    blocked_actions = [
        step
        for step in steps
        if step["tool_spec"]["status"] == "missing_tool_spec"
    ]
    coverage_audit = audit_tool_coverage()

    return {
        "task_id": _task_id(task),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "route": route,
        "steps": steps,
        "blocked_actions": blocked_actions,
        "tool_coverage_summary": {
            "surface_count": coverage_audit["surface_count"],
            "active_surface_count": coverage_audit["active_surface_count"],
            "covered_count": coverage_audit["covered_count"],
            "missing_count": coverage_audit["missing_count"],
            "stale_surface_count": coverage_audit["stale_surface_count"],
            "missing_by_priority": coverage_audit["missing_by_priority"],
        },
        "phase_order": ["route", "explore", "implement", "verify", "governance"],
        "tool_spec_policy": (
            "Executable actions must name a ToolSpec. Steps marked "
            "missing_tool_spec are planning debt, not permission to run scripts."
        ),
        "verification_policy": (
            "PASS requires observed tool or command evidence and must remain "
            "separate from implementation."
        ),
    }
