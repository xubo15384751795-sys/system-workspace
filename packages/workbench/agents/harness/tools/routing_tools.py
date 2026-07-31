"""routing_tools — governed routing tools for the agent harness."""

from __future__ import annotations

import sys
from pathlib import Path

from tools.coverage_audit import audit_tool_coverage
from tools.registry import ToolResult, ToolSpec, _register
from tools.task_planner import create_task_plan
from tools.task_router import resolve_execution_authority, route_task

HARNESS_ROOT = Path(__file__).resolve().parent.parent

def _coerce_artifacts(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [str(raw)]


def _h_route_task(input: dict, dry_run: bool) -> ToolResult:
    task = input.get("task") or input.get("prompt") or input.get("query") or ""
    positional = input.get("positional_args", [])
    if not task and isinstance(positional, list):
        task = " ".join(str(part) for part in positional)
    task = str(task).strip()
    if not task:
        return ToolResult(
            ok=False,
            tool_id="routing.route_task",
            errors=["routing.route_task requires task=<text> or positional task text"],
        )

    artifacts = _coerce_artifacts(input.get("artifacts"))
    if dry_run:
        return ToolResult(
            ok=True,
            tool_id="routing.route_task",
            summary=f"[DRY RUN] route task: {task[:80]}",
        )

    decision = route_task(task, artifacts)
    return ToolResult(
        ok=True,
        tool_id="routing.route_task",
        summary=(
            f"Route to {decision['primary_module']} "
            f"({decision['context_file']}); mode={decision['recommended_mode']}"
        ),
        evidence={"routing_decision": decision},
        warnings=decision.get("escalation_reasons", []),
    )


_register(ToolSpec(
    id="routing.route_task",
    description=(
        "Route a fuzzy user task to the smallest owning module, context file, "
        "expert activations, policy mode, and verification expectations"
    ),
    subsystem="cc_switch",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "plan", "verify", "implement", "run", "edit", "fetch"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_route_task,
))


def _h_create_task_plan(input: dict, dry_run: bool) -> ToolResult:
    task = input.get("task") or input.get("prompt") or input.get("query") or ""
    positional = input.get("positional_args", [])
    if not task and isinstance(positional, list):
        task = " ".join(str(part) for part in positional)
    task = str(task).strip()
    if not task:
        return ToolResult(
            ok=False,
            tool_id="routing.create_task_plan",
            errors=["routing.create_task_plan requires task=<text> or positional task text"],
        )

    artifacts = _coerce_artifacts(input.get("artifacts"))
    if dry_run:
        return ToolResult(
            ok=True,
            tool_id="routing.create_task_plan",
            summary=f"[DRY RUN] create task plan: {task[:80]}",
        )

    plan = create_task_plan(task, artifacts)
    blocked_count = len(plan["blocked_actions"])
    return ToolResult(
        ok=True,
        tool_id="routing.create_task_plan",
        summary=(
            f"Task plan {plan['task_id']}: {len(plan['steps'])} steps, "
            f"{blocked_count} missing ToolSpec binding(s)"
        ),
        evidence={"task_plan": plan},
        warnings=[
            f"{blocked_count} step(s) require ToolSpec coverage before execution"
        ] if blocked_count else [],
    )


_register(ToolSpec(
    id="routing.create_task_plan",
    description=(
        "Create a structured checklist from a fuzzy task, with owner module, "
        "phase, mode, ToolSpec candidates, risk category, gates, and verification"
    ),
    subsystem="cc_switch",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "plan", "verify", "implement", "run", "edit", "fetch"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_create_task_plan,
))


def _h_tool_coverage_audit(input: dict, dry_run: bool) -> ToolResult:
    if dry_run:
        return ToolResult(
            ok=True,
            tool_id="routing.tool_coverage_audit",
            summary="[DRY RUN] audit ToolSpec coverage",
        )

    audit = audit_tool_coverage()
    missing_count = audit["missing_count"]
    stale_count = audit["stale_surface_count"]
    return ToolResult(
        ok=True,
        tool_id="routing.tool_coverage_audit",
        summary=(
            f"ToolSpec coverage: {audit['covered_count']}/{audit['active_surface_count']} "
            f"active surfaces covered; {missing_count} missing; {stale_count} stale rules"
        ),
        evidence={"tool_coverage_audit": audit},
        warnings=(
            ([f"{missing_count} governed surface(s) still need ToolSpec coverage"] if missing_count else [])
            + ([f"{stale_count} coverage rule(s) point to removed scripts"] if stale_count else [])
        ),
    )


_register(ToolSpec(
    id="routing.tool_coverage_audit",
    description=(
        "Audit key workspace scripts and release/promotion surfaces for missing "
        "ToolSpec coverage"
    ),
    subsystem="cc_switch",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "plan", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_tool_coverage_audit,
))


def _h_execute_pipeline_step(input: dict, dry_run: bool) -> ToolResult:
    step_id = str(input.get("step_id") or input.get("step") or "").strip()
    mode = str(input.get("mode") or "run")
    task = str(input.get("task") or "").strip()

    positional = input.get("positional_args", [])
    if not step_id and isinstance(positional, list):
        if positional:
            step_id = str(positional[0]).strip()
        if len(positional) > 1 and not task:
            task = " ".join(str(part) for part in positional[1:])

    if not step_id:
        return ToolResult(
            ok=False,
            tool_id="routing.execute_pipeline_step",
            errors=["routing.execute_pipeline_step requires step_id=<registry_step>"],
        )

    authority = resolve_execution_authority(mode, step_id=step_id)
    if dry_run:
        return ToolResult(
            ok=True,
            tool_id="routing.execute_pipeline_step",
            summary=f"[DRY RUN] would execute pipeline step {step_id}",
            evidence={"execution_authority": authority, "step_id": step_id},
        )
    if not authority["may_dry_run_pipeline_step"] and str(input.get("pipeline_dry_run", "false")).lower() in ("true", "1", "yes"):
        return ToolResult(
            ok=False,
            tool_id="routing.execute_pipeline_step",
            errors=[f"dry-run denied for tier {authority['authority_tier']}"],
            evidence={"execution_authority": authority},
        )
    if not authority["may_execute_pipeline_step"]:
        return ToolResult(
            ok=False,
            tool_id="routing.execute_pipeline_step",
            errors=authority["reasons"] or [f"execution denied for tier {authority['authority_tier']}"],
            evidence={"execution_authority": authority},
        )

    if str(HARNESS_ROOT) not in sys.path:
        sys.path.insert(0, str(HARNESS_ROOT))
    from tools.registry import run_tool

    pipeline_dry_run = str(input.get("pipeline_dry_run", "false")).lower() in ("true", "1", "yes")
    result = run_tool(
        "workbench.run_pipeline_step",
        {"step_id": step_id, "mode": mode, "dry_run": str(pipeline_dry_run).lower()},
        mode=mode,
        dry_run=False,
    )
    evidence = {
        **(result.get("evidence") or {}),
        "execution_authority": authority,
    }
    if task:
        evidence["routing_context"] = route_task(task, [])
    return ToolResult(
        ok=bool(result.get("ok")),
        tool_id="routing.execute_pipeline_step",
        summary=result.get("summary", ""),
        artifacts=result.get("artifacts", []),
        evidence=evidence,
        warnings=result.get("warnings", []),
        errors=result.get("errors", []),
    )


_register(ToolSpec(
    id="routing.execute_pipeline_step",
    description=(
        "Execute a governed daily pipeline step when routing authority allows; "
        "enforces agent_routing_authority.yaml tier policy"
    ),
    subsystem="cc_switch",
    risk_level="medium",
    read_only=False,
    mutates_artifacts=True,
    requires_approval=False,
    allowed_modes=["verify", "run", "edit", "fetch"],
    required_prechecks=["routing.route_task"],
    postchecks=["write_event"],
    handler=_h_execute_pipeline_step,
))
