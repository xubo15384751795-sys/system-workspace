"""coverage_audit — find workspace actions that are not governed by ToolSpec."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.registry import list_tools


HARNESS_ROOT = Path(__file__).resolve().parent.parent


def _find_workspace_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "governance").is_dir() and (candidate / "scripts").is_dir():
            return candidate
    raise RuntimeError(f"Cannot locate workspace root from {start}")


WORKSPACE_ROOT = _find_workspace_root(HARNESS_ROOT)


@dataclass(frozen=True)
class SurfaceRule:
    script: str
    expected_tool_ids: list[str]
    subsystem: str
    risk_category: str
    priority: str
    rationale: str


SURFACE_RULES: list[SurfaceRule] = [
    SurfaceRule(
        script="scripts/promote_snapshot.py",
        expected_tool_ids=["artifact.promote_snapshot"],
        subsystem="data_output",
        risk_category="snapshot_publish",
        priority="critical",
        rationale="Archived v1 promotion is denied; the governed surface is artifact.promote_snapshot (quarantine/inspect), not a live deformation.promote_snapshot.",
    ),
    SurfaceRule(
        script="scripts/validate_workbench_contract.py",
        expected_tool_ids=["protocols.validate_contract", "workbench.validate_contract"],
        subsystem="protocols",
        risk_category="read_only",
        priority="high",
        rationale="Contract validation is a verification primitive that task plans should bind to.",
    ),
    SurfaceRule(
        script="scripts/build_system_index.py",
        expected_tool_ids=["artifact.build_system_index", "data_output.build_system_index"],
        subsystem="data_output",
        risk_category="data_mutation",
        priority="high",
        rationale="System index generation writes durable index artifacts.",
    ),
    SurfaceRule(
        script="scripts/list_latest.py",
        expected_tool_ids=["artifact.list_latest", "data_output.list_latest"],
        subsystem="data_output",
        risk_category="read_only",
        priority="medium",
        rationale="Latest symlink resolution should be a governed read-only primitive.",
    ),
    SurfaceRule(
        script="scripts/refresh_output_current.py",
        expected_tool_ids=["workbench.refresh_current", "artifact.refresh_current"],
        subsystem="workbench",
        risk_category="data_mutation",
        priority="high",
        rationale="Output/current refresh mutates the user-facing current surface.",
    ),
    SurfaceRule(
        script="scripts/build_artifact_navigator.py",
        expected_tool_ids=["workbench.build_artifact_navigator"],
        subsystem="workbench",
        risk_category="data_mutation",
        priority="medium",
        rationale="Artifact navigation build should be traceable through registry execution.",
    ),
    SurfaceRule(
        script="scripts/build_benchmark_evidence_dashboard.py",
        expected_tool_ids=["workbench.build_evidence_dashboard"],
        subsystem="workbench",
        risk_category="data_mutation",
        priority="medium",
        rationale="Evidence dashboard generation writes user-facing workbench artifacts.",
    ),
    SurfaceRule(
        script="scripts/system_status.py",
        expected_tool_ids=["workbench.system_status"],
        subsystem="workbench",
        risk_category="read_only",
        priority="medium",
        rationale="Status inspection should be available as a governed read-only tool.",
    ),
    SurfaceRule(
        script="scripts/archive/openbb_secondary_audit.py",
        expected_tool_ids=["learning_hub.openbb_secondary_audit"],
        subsystem="learning_hub",
        risk_category="read_only",
        priority="medium",
        rationale="OpenBB observe-only audit should emit governed Learning Hub evidence.",
    ),
    SurfaceRule(
        script="packages/workbench/agents/harness/tools/deformation_tools.py",
        expected_tool_ids=["deformation.evaluate_replay"],
        subsystem="deformation",
        risk_category="read_only",
        priority="high",
        rationale="Replay evaluation is verification evidence and should be ToolSpec-bound.",
    ),
    SurfaceRule(
        script="scripts/run_pipeline_step.py",
        expected_tool_ids=["workbench.run_pipeline_step", "routing.execute_pipeline_step"],
        subsystem="workbench",
        risk_category="data_mutation",
        priority="high",
        rationale="Single-step pipeline execution must route through governed ToolSpec.",
    ),
]


def _registered_tool_ids() -> set[str]:
    # Direct unit imports of this module do not pass through entrypoints/system.py,
    # so load registration side effects here as well.
    import tools.artifact_tools  # noqa: F401
    import tools.deformation_tools  # noqa: F401
    import tools.harvester_tools  # noqa: F401
    import tools.learning_hub_tools  # noqa: F401
    import tools.protocol_tools  # noqa: F401
    import tools.routing_tools  # noqa: F401
    import tools.workbench_tools  # noqa: F401
    # Resolve list_tools from the currently owned tools package. Repo-root
    # tools/ and harness tools/ share the import name; a module-level binding
    # can point at a stale registry after ownership switches in tests.
    from tools.registry import list_tools as _list_tools

    ids: set[str] = set()
    for mode in ["explore", "verify", "implement", "run", "edit", "fetch", "release", "plan"]:
        for spec in _list_tools(mode=mode):
            ids.add(spec.id)
    return ids


def audit_tool_coverage() -> dict[str, Any]:
    """Return a deterministic audit of scripts that need ToolSpec coverage."""
    registered = _registered_tool_ids()
    surfaces: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    covered: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []

    for rule in SURFACE_RULES:
        path = WORKSPACE_ROOT / rule.script
        exists = path.is_file()
        matched = sorted(tool_id for tool_id in rule.expected_tool_ids if tool_id in registered)
        if not exists:
            coverage = "stale_surface"
        elif matched:
            coverage = "covered"
        else:
            coverage = "missing_tool_spec"
        item = {
            "script": rule.script,
            "exists": exists,
            "subsystem": rule.subsystem,
            "risk_category": rule.risk_category,
            "priority": rule.priority,
            "expected_tool_ids": rule.expected_tool_ids,
            "matched_tool_ids": matched,
            "coverage": coverage,
            "rationale": rule.rationale,
        }
        surfaces.append(item)
        if coverage == "covered":
            covered.append(item)
        elif coverage == "missing_tool_spec":
            missing.append(item)
        else:
            stale.append(item)

    by_priority: dict[str, int] = {}
    for item in missing:
        priority = str(item.get("priority", "unknown"))
        by_priority[priority] = by_priority.get(priority, 0) + 1

    return {
        "registered_tool_count": len(registered),
        "registered_tool_ids": sorted(registered),
        "surface_count": len(surfaces),
        "active_surface_count": len(surfaces) - len(stale),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "stale_surface_count": len(stale),
        "missing_by_priority": by_priority,
        "surfaces": surfaces,
        "missing_surfaces": missing,
        "stale_surfaces": stale,
        "covered_surfaces": covered,
        "policy": (
            "Critical or high-priority missing_tool_spec surfaces should be wrapped "
            "before agents use their underlying scripts for execution."
        ),
    }
