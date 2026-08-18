#!/usr/bin/env python3
"""Regenerate Data/system_index/ from authoritative artifacts.

Inputs read:
  - Data/harvester/exports/<release_id>/catalog.json (each release dir)
  - Output/deformation_runs/<run_id>/run_manifest.json (each run dir)
  - Data/deformation/snapshots/index.json
  - Output/system_learning/latest/summary.json
  - Output/sandbox/openbb/runs/<run_id>/run_manifest.json
  - Output/sandbox/qlib/runs/<run_id>/run_manifest.json

Outputs written:
  - Data/system_index/latest.json
  - Data/system_index/system_catalog.json
  - Data/system_index/lineage_graph.json

This is intentionally read-only with respect to subsystem source code.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from ._paths import (
    CANONICAL_SNAPSHOT_INDEX,
    DEFORMATION_RUNS,
    HARVESTER_EXPORTS,
    HARVESTER_LATEST,
    LEARNING_SUMMARY,
    LINEAGE_GRAPH,
    SANDBOX_OPENBB_RUNS,
    SANDBOX_QLIB_RUNS,
    SYSTEM_CATALOG,
    SYSTEM_INDEX_DIR,
    SYSTEM_LATEST,
    WORKSPACE_ROOT,
)


def _ws_rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(p)


def _read_json(p: Path) -> dict[str, Any] | None:
    if not p.exists():
        return None
    try:
        return cast(dict[str, Any], json.loads(p.read_text()))
    except json.JSONDecodeError:
        return None


def _harvester_releases() -> list[dict]:
    if not HARVESTER_EXPORTS.exists():
        return []
    out: list[dict] = []
    for d in sorted(HARVESTER_EXPORTS.iterdir()):
        if not d.is_dir() or d.is_symlink():
            continue
        catalog = _read_json(d / "catalog.json") or {}
        out.append({
            "release_id": d.name,
            "path": _ws_rel(d),
            "catalog_path": _ws_rel(d / "catalog.json"),
            "status": catalog.get("status", "unknown"),
            "files": [f.get("path") for f in catalog.get("files", []) if isinstance(f, dict)],
        })
    return out


def _resolved_latest_release_id() -> str | None:
    if not HARVESTER_LATEST.exists():
        return None
    return HARVESTER_LATEST.resolve().name


def _deformation_runs() -> list[dict]:
    if not DEFORMATION_RUNS.exists():
        return []
    out: list[dict] = []
    for d in sorted(DEFORMATION_RUNS.iterdir()):
        if not d.is_dir() or d.is_symlink():
            continue
        manifest = _read_json(d / "run_manifest.json") or {}
        gaps: list[str] = []
        if not (d / "config_snapshot.json").exists():
            gaps.append("config_snapshot.json missing")
        else:
            cs = _read_json(d / "config_snapshot.json") or {}
            if cs.get("captured_status") == "missing":
                gaps.append("config_snapshot captured retroactively")
        trace = d / "traces" / "operator_trace.jsonl"
        if not trace.exists():
            gaps.append("operator_trace.jsonl missing")
        else:
            first = trace.open().readline()
            if first and '"status": "missing"' in first:
                gaps.append("operator_trace marked missing in header")

        promoted = bool(manifest.get("promotion", {}).get("snapshot_promoted"))
        promotion = manifest.get("promotion", {}) if isinstance(manifest.get("promotion"), dict) else {}
        out.append({
            "run_id": d.name,
            "path": _ws_rel(d),
            "harvester_release": manifest.get("harvester_release"),
            "snapshot_path": _ws_rel(d / "machine" / "snapshot.json"),
            "canonical_snapshot_id": promotion.get("canonical_snapshot_id"),
            "quarantine_snapshot_id": promotion.get("quarantine_snapshot_id"),
            "snapshot_promoted": promoted,
            "snapshot_status": promotion.get("snapshot_status", "canonical" if promoted else None),
            "claim_carrying_allowed": bool(promotion.get("claim_carrying_allowed", promoted)),
            "status": manifest.get("status", "unknown"),
            "freshness_manifest_path": _ws_rel(d / "freshness_manifest.json") if (d / "freshness_manifest.json").exists() else None,
            "model_input_validity": manifest.get("model_input_validity"),
            "freshness_gate_result": manifest.get("freshness_gate_result"),
            "gaps": gaps,
        })
    return out


def _latest_run(runs: list[dict]) -> dict | None:
    return runs[-1] if runs else None


def _sandbox_latest(runs_dir: Path) -> dict | None:
    if not runs_dir.exists():
        return None
    cands = sorted(d for d in runs_dir.iterdir() if d.is_dir() and not d.is_symlink())
    if not cands:
        return None
    last = cands[-1]
    manifest = _read_json(last / "run_manifest.json") or {}
    return {
        "run_id": last.name,
        "path": _ws_rel(last),
        "status": manifest.get("status", "unknown"),
    }


def _learning() -> dict:
    summary = _read_json(LEARNING_SUMMARY) or {}
    return {
        "summary_path": _ws_rel(LEARNING_SUMMARY) if LEARNING_SUMMARY.exists() else None,
        "band": summary.get("overall", {}).get("band"),
        "events": summary.get("overall", {}).get("events_observed"),
        "open_improvements": summary.get("improvement_queue", {}).get("proposed", 0)
        + summary.get("improvement_queue", {}).get("approved", 0),
    }


def _snapshot_index_entries() -> list[dict]:
    idx = _read_json(CANONICAL_SNAPSHOT_INDEX) or {}
    return idx.get("snapshots", []) or []


def _canonical_snapshots() -> list[dict]:
    return [entry for entry in _snapshot_index_entries() if entry.get("status") == "canonical"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build() -> None:
    """Rebuild Data/system_index/ from authoritative artifacts.

    Writes latest.json, system_catalog.json, and lineage_graph.json.
    Reads from harvester exports, deformation runs, snapshot index, and
    learning hub summary.
    """
    SYSTEM_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    now = _now()

    releases = _harvester_releases()
    runs = _deformation_runs()
    snapshot_entries = _snapshot_index_entries()
    snapshots = [entry for entry in snapshot_entries if entry.get("status") == "canonical"]
    learning = _learning()

    latest_release = next(
        (r for r in releases if r["release_id"] == _resolved_latest_release_id()),
        releases[-1] if releases else None,
    )
    latest_run = _latest_run(runs)
    openbb_latest = _sandbox_latest(SANDBOX_OPENBB_RUNS)
    qlib_latest = _sandbox_latest(SANDBOX_QLIB_RUNS)

    canonical_snapshot = snapshots[-1] if snapshots else None

    latest_payload = {
        "schema_version": "system.index.latest.v1",
        "updated_at": now,
        "updated_by": "scripts/build_system_index.py",
        "latest": {
            "harvester_release": (
                {
                    "id": latest_release["release_id"],
                    "path": latest_release["path"],
                    "catalog_path": latest_release["catalog_path"],
                    "status": latest_release["status"],
                }
                if latest_release
                else None
            ),
            "deformation_run": (
                {
                    "id": latest_run["run_id"],
                    "path": latest_run["path"],
                    "run_manifest_path": f"{latest_run['path']}/run_manifest.json",
                    "harvester_release": latest_run["harvester_release"],
                    "status": latest_run["status"],
                    "gaps": latest_run["gaps"],
                }
                if latest_run
                else None
            ),
            "deformation_snapshot": (
                {
                    "id": canonical_snapshot.get("snapshot_id"),
                    "path": canonical_snapshot.get("snapshot_path"),
                    "status": canonical_snapshot.get("status", "canonical"),
                }
                if canonical_snapshot
                else {
                    "id": None,
                    "path": None,
                    "status": "no_canonical_snapshot",
                    "reason": "No deformation run has been promoted yet. Use scripts/promote_snapshot.py once a run is judged canonical.",
                }
            ),
            "learning_report": {
                "summary_path": learning["summary_path"],
                "health_report_path": "Output/system_learning/latest/system_health_report.md",
                "band": learning["band"],
            },
            "sandbox": {
                "openbb_latest_run": openbb_latest,
                "qlib_latest_run": qlib_latest,
            },
        },
    }

    catalog_payload = {
        "schema_version": "system.catalog.v1",
        "generated_at": now,
        "generated_by": "scripts/build_system_index.py",
        "harvester_releases": releases,
        "deformation_runs": runs,
        "deformation_canonical_snapshots": snapshots,
        "deformation_snapshot_entries": snapshot_entries,
        "learning_hub": {
            "ledgers_dir": "Data/system_learning/ledgers",
            "registries_dir": "Data/system_learning/registries",
            "latest_summary": learning["summary_path"],
            "latest_health_report": "Output/system_learning/latest/system_health_report.md",
            "events_dir": "Output/system_learning/events",
            "routing_decisions_dir": "Output/system_learning/routing_decisions",
        },
        "sandbox": {
            "openbb_runs_dir": _ws_rel(SANDBOX_OPENBB_RUNS),
            "qlib_runs_dir": _ws_rel(SANDBOX_QLIB_RUNS),
        },
    }

    nodes: list[dict] = []
    edges: list[dict] = []
    for r in releases:
        nodes.append({"id": f"harvester_release:{r['release_id']}", "kind": "harvester_release", "path": r["path"]})
    for run in runs:
        nodes.append({"id": f"deformation_run:{run['run_id']}", "kind": "deformation_run", "path": run["path"]})
        if run["harvester_release"]:
            edges.append({
                "from": f"harvester_release:{run['harvester_release']}",
                "to": f"deformation_run:{run['run_id']}",
                "relation": "input_to",
            })
        if run["snapshot_promoted"] and run["canonical_snapshot_id"] and run.get("claim_carrying_allowed"):
            nodes.append({
                "id": f"snapshot:{run['canonical_snapshot_id']}",
                "kind": "structural_snapshot",
                "path": f"Data/deformation/snapshots/{run['canonical_snapshot_id']}.json",
            })
            edges.append({
                "from": f"deformation_run:{run['run_id']}",
                "to": f"snapshot:{run['canonical_snapshot_id']}",
                "relation": "produced",
            })
        elif run.get("quarantine_snapshot_id"):
            nodes.append({
                "id": f"snapshot_quarantine:{run['quarantine_snapshot_id']}",
                "kind": "structural_snapshot_quarantine",
                "path": f"Data/deformation/quarantine/snapshots/{run['quarantine_snapshot_id']}.json",
            })
            edges.append({
                "from": f"deformation_run:{run['run_id']}",
                "to": f"snapshot_quarantine:{run['quarantine_snapshot_id']}",
                "relation": "preserved_non_claim_evidence",
            })
    if learning["summary_path"]:
        nodes.append({"id": "learning_report:latest", "kind": "learning_report", "path": "Output/system_learning/latest"})
        for run in runs:
            edges.append({
                "from": f"deformation_run:{run['run_id']}",
                "to": "learning_report:latest",
                "relation": "emitted_events_to",
            })

    lineage_payload = {
        "schema_version": "system.lineage.v1",
        "generated_at": now,
        "nodes": nodes,
        "edges": edges,
    }

    SYSTEM_LATEST.write_text(json.dumps(latest_payload, indent=2) + "\n")
    SYSTEM_CATALOG.write_text(json.dumps(catalog_payload, indent=2) + "\n")
    LINEAGE_GRAPH.write_text(json.dumps(lineage_payload, indent=2) + "\n")
    print(f"Wrote {_ws_rel(SYSTEM_LATEST)}")
    print(f"Wrote {_ws_rel(SYSTEM_CATALOG)}")
    print(f"Wrote {_ws_rel(LINEAGE_GRAPH)}")


def main() -> int:
    """CLI entry point — build system index and return exit code."""
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
