"""artifact_tools — governed artifact state-transition tools."""

from __future__ import annotations

import json
import shutil
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from tools.registry import ToolResult, ToolSpec, _register


HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
def _resolve_system_root(workbench_root: Path) -> Path:
    """Repo root for both legacy `Workbench/` and `packages/workbench` layouts."""
    parent = workbench_root.parent
    if workbench_root.name.lower() == "workbench" and parent.name == "packages":
        return parent.parent
    return parent

WORKSPACE_ROOT = _resolve_system_root(WORKBENCH_ROOT)
WORKBENCH_SRC = WORKBENCH_ROOT / "src"


def _promoter_module():
    if str(WORKBENCH_SRC) not in sys.path:
        sys.path.insert(0, str(WORKBENCH_SRC))
    from workbench.workspace import promote_snapshot

    return promote_snapshot


def _system_index_module():
    if str(WORKBENCH_SRC) not in sys.path:
        sys.path.insert(0, str(WORKBENCH_SRC))
    from workbench.workspace import build_system_index

    return build_system_index


def _preflight(run_id: str, snapshot_id: str, force: bool) -> dict[str, Any]:
    promoter = _promoter_module()
    run_dir = promoter.DEFORMATION_RUNS / run_id
    routing = _routing_preflight(promoter, run_id, snapshot_id)
    if not run_dir.exists():
        return {
            "ok": False,
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "blockers": [f"run dir does not exist: {run_dir}", *routing.get("blockers", [])],
            "run_path": f"archive_run:{run_id}",
            "routing_decision": routing,
        }

    try:
        manifest, blockers = promoter._check(run_dir, True)
    except Exception as exc:  # noqa: BLE001 - convert tool preflight to evidence
        return {
            "ok": False,
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "blockers": [str(exc)],
            "run_path": f"archive_run:{run_id}",
        }

    provenance_status = promoter._provenance_status(run_dir, manifest)
    known_limitations = promoter._known_provenance_limitations(provenance_status)
    hard_blocked = bool(blockers and not force)
    routing_blocked = not bool(routing.get("ok"))
    target = promoter.CANONICAL_SNAPSHOTS / f"{snapshot_id}.json"
    return {
        "ok": not hard_blocked and not routing_blocked,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "run_path": f"archive_run:{run_id}",
        "target_snapshot_path": f"Data/deformation/snapshots/{snapshot_id}.json",
        "target_exists": target.exists(),
        "force": force,
        "blockers": [*blockers, *routing.get("blockers", [])],
        "provenance_status": provenance_status,
        "known_provenance_limitations": known_limitations,
        "routing_decision": routing,
        "manual_review_required": True,
    }


def _promote(run_id: str, snapshot_id: str, force: bool) -> dict[str, Any]:
    promoter = _promoter_module()
    run_dir = promoter.DEFORMATION_RUNS / run_id
    if not run_dir.exists():
        raise RuntimeError(f"run dir does not exist: {run_dir}")

    try:
        routing_decision = promoter._enforce_routing_decision(run_id, snapshot_id)
        manifest, blockers = promoter._check(run_dir, force)
        authority_config_events = promoter._audit_force_promotion(run_id, force)
    except SystemExit as exc:
        raise RuntimeError(str(exc)) from exc

    provenance_status = promoter._provenance_status(run_dir, manifest)
    known_limitations = promoter._known_provenance_limitations(provenance_status)
    status = promoter._promotion_status(force, blockers)

    target = promoter._snapshot_target(snapshot_id, status)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_dir / "machine" / "snapshot.json", target)

    if promoter.CANONICAL_SNAPSHOT_INDEX.exists():
        idx = json.loads(promoter.CANONICAL_SNAPSHOT_INDEX.read_text())
    else:
        idx = {"schema_version": "deformation.snapshot_index.v1", "snapshots": []}

    entry = {
        "snapshot_id": snapshot_id,
        "source_run_id": run_id,
        "source_run_path": f"Output/deformation_runs/{run_id}",
        "harvester_release": manifest.get("harvester_release"),
        "snapshot_path": promoter._snapshot_path_text(snapshot_id, status),
        "status": status,
        "promoted_at": promoter._now(),
        "force_promoted": bool(force),
        "promotion_blockers": blockers if force else [],
        "claim_carrying_allowed": promoter._claim_carrying_allowed(status),
        "config_hash": manifest.get("config_hash"),
        "config_snapshot_status": provenance_status.get("config_snapshot"),
        "output_manifest": f"Output/deformation_runs/{run_id}/artifacts.json",
        "provenance_status": provenance_status,
        "known_provenance_limitations": known_limitations,
        "routing_decision": routing_decision,
        "authority_config_events": authority_config_events,
    }
    promoter._write_snapshot_index(idx, entry)

    manifest.setdefault("promotion", {})
    manifest["promotion"]["snapshot_promoted"] = status == "canonical"
    manifest["promotion"]["snapshot_status"] = status
    manifest["promotion"]["claim_carrying_allowed"] = promoter._claim_carrying_allowed(status)
    manifest["promotion"]["canonical_snapshot_id"] = snapshot_id if status == "canonical" else None
    manifest["promotion"]["quarantine_snapshot_id"] = snapshot_id if status != "canonical" else None
    manifest["promotion"]["promoted_at"] = promoter._now()
    manifest["promotion"]["force_promoted"] = bool(force)
    manifest["promotion"]["promotion_blockers"] = blockers if force else []
    manifest["promotion"]["provenance_status"] = provenance_status
    manifest["promotion"]["known_provenance_limitations"] = known_limitations
    manifest["promotion"]["routing_decision"] = routing_decision
    manifest["promotion"]["authority_config_events"] = authority_config_events
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    from workbench.workspace.build_system_index import build

    build()
    return {
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "target_snapshot_path": promoter._snapshot_path_text(snapshot_id, status),
        "index_path": "Data/deformation/snapshots/index.json",
        "force": force,
        "status": status,
        "claim_carrying_allowed": promoter._claim_carrying_allowed(status),
        "blockers": blockers,
        "provenance_status": provenance_status,
        "known_provenance_limitations": known_limitations,
        "routing_decision": routing_decision,
        "authority_config_events": authority_config_events,
    }


def _routing_preflight(promoter: Any, run_id: str, snapshot_id: str) -> dict[str, Any]:
    decision_path, payload = promoter._latest_promotion_routing_decision()
    gate = payload.get("promotion_gate_decision") if payload else None
    may_promote = gate.get("may_promote_current_snapshot") if isinstance(gate, dict) else None
    decision_id = payload.get("decision_id") or payload.get("task_id") or (decision_path.stem if decision_path else None)
    try:
        promoter.assert_promotion_allowed(promoter.ROUTING_DECISIONS)
        ok = True
        blocker = None
    except Exception as exc:  # noqa: BLE001 - preflight converts gate failure to evidence
        ok = False
        blocker = str(exc)
    return {
        "ok": ok,
        "decision_id": decision_id,
        "decision_path": str(decision_path.relative_to(promoter.WORKSPACE_ROOT)) if decision_path else None,
        "may_promote_current_snapshot": may_promote,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "blockers": [] if blocker is None else [blocker],
    }


def _h_promote_snapshot(input: dict, dry_run: bool) -> ToolResult:
    run_id = str(input.get("run_id") or input.get("run") or "").strip()
    if not run_id:
        return ToolResult(
            ok=False,
            tool_id="artifact.promote_snapshot",
            errors=["artifact.promote_snapshot requires run_id=<archived run id>"],
        )

    snapshot_id = str(input.get("snapshot_id") or f"snapshot_{run_id}").strip()
    force = str(input.get("force", "false")).lower() in {"1", "true", "yes"}
    preflight = _preflight(run_id, snapshot_id, force)

    if dry_run:
        return ToolResult(
            ok=True,
            tool_id="artifact.promote_snapshot",
            summary=(
                f"[DRY RUN] Promotion preflight for {run_id}: "
                f"{'ready' if preflight['ok'] else 'blocked'}"
            ),
            evidence={"preflight": preflight},
            warnings=preflight.get("blockers", []),
        )

    if not preflight["ok"]:
        return ToolResult(
            ok=False,
            tool_id="artifact.promote_snapshot",
            summary=f"Promotion blocked for {run_id}",
            evidence={"preflight": preflight},
            errors=preflight.get("blockers", []),
        )

    result = _promote(run_id, snapshot_id, force)
    return ToolResult(
        ok=True,
        tool_id="artifact.promote_snapshot",
        summary=f"Promoted {run_id} to {result['target_snapshot_path']}",
        artifacts=[result["target_snapshot_path"], result["index_path"]],
        evidence={"promotion": result},
        warnings=result.get("known_provenance_limitations", []),
    )


def _h_promote_snapshot_preflight(input: dict, dry_run: bool) -> ToolResult:
    run_id = str(input.get("run_id") or input.get("run") or "").strip()
    if not run_id:
        return ToolResult(
            ok=False,
            tool_id="artifact.promote_snapshot_preflight",
            errors=["artifact.promote_snapshot_preflight requires run_id=<archived run id>"],
        )

    snapshot_id = str(input.get("snapshot_id") or f"snapshot_{run_id}").strip()
    force = str(input.get("force", "false")).lower() in {"1", "true", "yes"}
    preflight = _preflight(run_id, snapshot_id, force)
    return ToolResult(
        ok=True,
        tool_id="artifact.promote_snapshot_preflight",
        summary=(
            f"Promotion preflight for {run_id}: "
            f"{'ready' if preflight['ok'] else 'blocked'}"
        ),
        evidence={"preflight": preflight},
        warnings=preflight.get("blockers", []),
    )


def _h_build_system_index(input: dict, dry_run: bool) -> ToolResult:
    builder = _system_index_module()
    output_paths = [
        builder.SYSTEM_LATEST,
        builder.SYSTEM_CATALOG,
        builder.LINEAGE_GRAPH,
    ]

    captured_stdout = StringIO()
    with redirect_stdout(captured_stdout):
        builder.build()

    artifacts = [
        str(path.resolve().relative_to(WORKSPACE_ROOT))
        for path in output_paths
    ]
    outputs = {
        artifact: {
            "exists": (WORKSPACE_ROOT / artifact).is_file(),
            "bytes": (WORKSPACE_ROOT / artifact).stat().st_size
            if (WORKSPACE_ROOT / artifact).is_file()
            else 0,
        }
        for artifact in artifacts
    }
    return ToolResult(
        ok=all(item["exists"] for item in outputs.values()),
        tool_id="data_output.build_system_index",
        summary="Built Data/system_index latest, catalog, and lineage artifacts",
        artifacts=artifacts,
        evidence={
            "system_index": {
                "outputs": outputs,
                "builder_stdout": [
                    line
                    for line in captured_stdout.getvalue().splitlines()
                    if line.strip()
                ],
            }
        },
        errors=[
            f"missing output: {artifact}"
            for artifact, item in outputs.items()
            if not item["exists"]
        ],
    )


_register(ToolSpec(
    id="artifact.promote_snapshot_preflight",
    description=(
        "Read-only preflight for snapshot promotion: checks run status, "
        "snapshot, config, trace, freshness, target path, and provenance limits"
    ),
    subsystem="data_output",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify", "release"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_promote_snapshot_preflight,
))


_register(ToolSpec(
    id="artifact.promote_snapshot",
    description=(
        "Quarantine or inspect an archived run snapshot. Canonical v1 promotion "
        "is denied; this is not a live current promote API."
    ),
    subsystem="data_output",
    risk_level="high",
    read_only=False,
    mutates_artifacts=True,
    requires_approval=True,
    allowed_modes=["release"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_promote_snapshot,
))


_register(ToolSpec(
    id="data_output.build_system_index",
    description=(
        "Build Data/system_index/latest.json, system_catalog.json, and "
        "lineage_graph.json from authoritative workspace artifacts"
    ),
    subsystem="data_output",
    risk_level="medium",
    read_only=False,
    mutates_artifacts=True,
    requires_approval=False,
    allowed_modes=["run", "release"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_build_system_index,
))
