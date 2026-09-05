#!/usr/bin/env python3
"""Inspect or quarantine an archived run snapshot after governance checks.

Canonical promotion of Deformation v1 is permanently denied. This CLI accepts
any archived run id as historical evidence; it is not a live promote API.

Usage:
    python3 scripts/promote_snapshot.py --run <archived_run_id> [--snapshot-id <id>] [--force]

Pre-conditions enforced:
  * the archived run's `run_manifest.json` exists and `status == "success"`.
  * `machine/snapshot.json` exists.
  * `traces/operator_trace.jsonl` exists and its first record is not a `status: missing` header.
  * `config_snapshot.json` exists with `captured_status == "captured"`.
  * Validation diagnostics are populated with benchmark/residual/gate evidence.

Force mode no longer creates a canonical snapshot. It preserves the artifact as
quarantine / legacy canonicalization evidence that can be replayed but cannot
carry paper-facing claims.

Effects:
  * Copies canonical snapshots to `Data/deformation/snapshots/<snapshot_id>.json`.
  * Copies forced snapshots to `Data/deformation/quarantine/snapshots/<snapshot_id>.json`.
  * Updates `Data/deformation/snapshots/index.json` (latest canonical + entries).
  * Updates `promotion` block in the source run_manifest.json.
  * Re-runs `build_system_index.py` so latest.json/system_catalog.json/lineage_graph.json reflect the new canonical artifact.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml

from system_runtime.paths import output_surface
from workbench.governance.authority import write_authority_event
from workbench.governance.config_audit import audit_config
from workbench.governance.decision_trace import record_decision
from workbench.governance.incident import create_or_update_incident
from workbench.governance.report_gate import validate_report_verdict
from workbench.governance.routing_gate import RoutingGateError, assert_promotion_allowed

from ._paths import (
    CANONICAL_SNAPSHOT_INDEX,
    CANONICAL_SNAPSHOTS,
    DEFORMATION_RUNS,
    QUARANTINE_SNAPSHOTS,
    WORKSPACE_ROOT,
)

logger = logging.getLogger(__name__)

ROUTING_DECISIONS = output_surface(WORKSPACE_ROOT, "system_learning") / "routing_decisions"
RECORD_RUNTIME_SCRIPT = WORKSPACE_ROOT / "scripts" / "record_runtime_event.py"
RUNTIME_LOG_DIR = output_surface(WORKSPACE_ROOT, "system_learning") / "runtime"
CONFIG_AUTHORITY_REGISTRY = WORKSPACE_ROOT / "governance" / "config_authority_registry.yaml"
AUTHORITY_TRACE = WORKSPACE_ROOT / "Output" / "governance" / "traces" / "authority_trace.jsonl"
GOVERNANCE_EVENTS = WORKSPACE_ROOT / "Output" / "governance" / "events"
INCIDENT_LEDGER = WORKSPACE_ROOT / "Output" / "governance" / "incidents.jsonl"
REPORTS_DIR = WORKSPACE_ROOT / "Output" / "reports"
SEMANTIC_REGISTRY = WORKSPACE_ROOT / "governance" / "semantic_registry.json"
ROUTING_DECISION_MAX_AGE_DAYS = 30


class PromotionError(Exception):
    """Raised when a promotion precondition fails — caught by tool handlers
    and converted to structured evidence instead of crashing the process."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(run_dir: Path, force: bool, run_id: str = "unknown") -> tuple[dict, list[str]]:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise PromotionError(f"run_manifest.json missing at {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    blockers: list[str] = []
    if manifest.get("status") != "success":
        blockers.append(f"run status is {manifest.get('status')!r}, not 'success'")

    backend = manifest.get("data_backend", "legacy")
    if backend == "legacy":
        blockers.append(
            "Data backend is 'legacy' which uses direct HTTP acquisition — "
            "forbidden by DATA_BOUNDARY.md. Re-run with data_backend: harvester."
        )

    snap = run_dir / "machine" / "snapshot.json"
    if not snap.exists():
        blockers.append(f"machine/snapshot.json missing at {snap}")
    cs_path = run_dir / "config_snapshot.json"
    if cs_path.exists():
        cs = json.loads(cs_path.read_text())
        if cs.get("captured_status") != "captured":
            blockers.append(f"config_snapshot.captured_status is {cs.get('captured_status')!r}")
    else:
        blockers.append("config_snapshot.json missing")
    trace_path = run_dir / "traces" / "operator_trace.jsonl"
    if trace_path.exists():
        first = trace_path.open().readline()
        if first and '"status": "missing"' in first:
            blockers.append("operator_trace.jsonl header marks the trace as missing")
    else:
        blockers.append("traces/operator_trace.jsonl missing")
    freshness_path = run_dir / "freshness_manifest.json"
    if freshness_path.exists():
        try:
            freshness = json.loads(freshness_path.read_text())
        except json.JSONDecodeError as exc:
            blockers.append(
                f"freshness_manifest.json is corrupt/unparseable: {exc}. "
                "Cannot verify data freshness — promotion blocked."
            )
            freshness = {}
        gate = freshness.get("gate_result")
        if gate is None or gate == {}:
            blockers.append(
                "freshness_manifest.json has empty or missing gate_result — "
                "freshness gate did not execute or returned no verdict."
            )
        elif isinstance(gate, dict):
            for blocker in gate.get("blockers", []) or []:
                blockers.append(f"freshness gate blocker: {blocker}")
        manifest.setdefault("freshness_gate_result", gate)
        manifest.setdefault("model_input_validity", freshness.get("model_input_validity"))
    else:
        blockers.append("freshness_manifest.json missing")

    diagnostic_blockers = _diagnostic_blockers(run_dir)
    blockers.extend(diagnostic_blockers)

    # Semantic registry must exist and be parseable — fail-closed
    if not SEMANTIC_REGISTRY.exists():
        blockers.append(
            f"Semantic registry missing at {SEMANTIC_REGISTRY.relative_to(WORKSPACE_ROOT)}. "
            "Cannot validate structural claims — promotion blocked."
        )
    else:
        try:
            semantic_data = json.loads(SEMANTIC_REGISTRY.read_text(encoding="utf-8"))
            if not isinstance(semantic_data, dict) or not semantic_data:
                blockers.append(
                    f"Semantic registry at {SEMANTIC_REGISTRY.relative_to(WORKSPACE_ROOT)} is empty or invalid. "
                    "Cannot validate structural claims — promotion blocked."
                )
        except json.JSONDecodeError as exc:
            blockers.append(
                f"Semantic registry at {SEMANTIC_REGISTRY.relative_to(WORKSPACE_ROOT)} is corrupt: {exc}. "
                "Cannot validate structural claims — promotion blocked."
            )

    # Write authority events for every blocker found (persistent governance trace)
    for blocker in blockers:
        write_authority_event(
            AUTHORITY_TRACE,
            run_id=run_id,
            module="promotion_gate",
            operation="_check",
            authority="PROMOTE",
            allowed=False,
            reason=blocker,
        )

    if blockers and not force:
        raise PromotionError(
            "Promotion blocked by pre-conditions:\n  - "
            + "\n  - ".join(blockers)
            + "\nRe-run with --force to override (and accept the gap)."
        )
    return manifest, blockers


def _diagnostic_blockers(run_dir: Path) -> list[str]:
    blockers: list[str] = []
    diagnostics_dir = run_dir / "diagnostics"
    tables_dir = run_dir / "tables"
    required_json = {
        "diagnostics/rejection_flags.json": diagnostics_dir / "rejection_flags.json",
        "diagnostics/residual_tests.json": diagnostics_dir / "residual_tests.json",
        "diagnostics/operator_diagnostics.json": diagnostics_dir / "operator_diagnostics.json",
    }
    for label, path in required_json.items():
        if not path.exists():
            blockers.append(f"{label} missing")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            blockers.append(f"{label} is corrupt/unparseable: {exc}")
            continue
        if not isinstance(payload, dict) or not payload:
            blockers.append(f"{label} is empty")

    validation_loop_path = diagnostics_dir / "validation_loop_status.json"
    if validation_loop_path.exists():
        try:
            validation_loop = json.loads(validation_loop_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            blockers.append(f"diagnostics/validation_loop_status.json is corrupt/unparseable: {exc}")
        else:
            if validation_loop.get("status") != "complete":
                blockers.append(
                    "diagnostics/validation_loop_status.json is not complete: "
                    f"{validation_loop.get('status', 'missing')}"
                )
            if validation_loop.get("claim_carrying_allowed") is not True:
                blockers.append("diagnostics/validation_loop_status.json does not allow claim carrying")
    else:
        blockers.append("diagnostics/validation_loop_status.json missing")

    comparison = tables_dir / "benchmark_comparison.csv"
    if not comparison.exists():
        blockers.append("tables/benchmark_comparison.csv missing")
    else:
        text = comparison.read_text(encoding="utf-8", errors="replace")
        if "not_available" in text:
            blockers.append("tables/benchmark_comparison.csv contains not_available")
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) <= 1:
            blockers.append("tables/benchmark_comparison.csv has no comparison rows")
    return blockers


def _promotion_status(force: bool, blockers: list[str]) -> str:
    if force:
        return "quarantine" if not blockers else "legacy_canonicalization"
    return "canonical"


def _claim_carrying_allowed(status: str) -> bool:
    return status == "canonical"


def _snapshot_target(snapshot_id: str, status: str) -> Path:
    if status == "canonical":
        return CANONICAL_SNAPSHOTS / f"{snapshot_id}.json"
    return QUARANTINE_SNAPSHOTS / f"{snapshot_id}.json"


def _snapshot_path_text(snapshot_id: str, status: str) -> str:
    if status == "canonical":
        return f"Data/deformation/snapshots/{snapshot_id}.json"
    return f"Data/deformation/quarantine/snapshots/{snapshot_id}.json"


def _write_snapshot_index(idx: dict[str, Any], entry: dict[str, Any]) -> None:
    snapshot_id = entry["snapshot_id"]
    idx["snapshots"] = [s for s in idx.get("snapshots", []) if s.get("snapshot_id") != snapshot_id] + [entry]
    if entry.get("status") == "canonical":
        idx["latest"] = snapshot_id
    else:
        idx["latest_quarantine"] = snapshot_id
        canonical = [s for s in idx["snapshots"] if s.get("status") == "canonical"]
        if canonical:
            idx["latest"] = canonical[-1].get("snapshot_id")
        else:
            idx["latest"] = None
    CANONICAL_SNAPSHOT_INDEX.write_text(json.dumps(idx, indent=2) + "\n")
    if entry.get("status") == "canonical":
        try:
            from orchestration.dvc_promote import record_snapshot_pointer

            target = CANONICAL_SNAPSHOTS / f"{snapshot_id}.json"
            dvc_result = record_snapshot_pointer(
                snapshot_id=snapshot_id,
                snapshot_path=target,
                index_path=CANONICAL_SNAPSHOT_INDEX,
            )
            if dvc_result.get("dvc_commit_status") != "PASS":
                logger.warning(
                    "DVC pointer not committed for snapshot %s: %s",
                    snapshot_id,
                    dvc_result.get("dvc_error", "DVC_COMMIT_BLOCKED"),
                )
        except Exception:
            logger.warning("Unable to record DVC snapshot pointer for %s", snapshot_id, exc_info=True)


def _append_system_event(event: dict[str, Any]) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = cast(Path, RUNTIME_LOG_DIR / f"records_{day}.jsonl")
    payload = {
        "event_id": f"snapshot_promotion_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_tool": "scripts.promote_snapshot",
        **event,
    }
    if RECORD_RUNTIME_SCRIPT.is_file():
        subprocess.run(
            [
                sys.executable,
                str(RECORD_RUNTIME_SCRIPT),
                "--system-root",
                str(WORKSPACE_ROOT),
                "--subsystem",
                "workbench",
                "--event-type",
                str(event.get("event_type") or "snapshot_publish_attempt"),
                "--severity",
                str(event.get("severity") or "info"),
                "--source-tool",
                "scripts.promote_snapshot",
                "--payload-json",
                json.dumps(payload, ensure_ascii=True, default=str),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    else:
        RUNTIME_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    # Auto-detect repeated critical findings → incident
    severity = str(event.get("severity", "")).upper()
    if severity in {"HIGH", "CRITICAL"}:
        finding = str(event.get("event_type") or event.get("finding") or "")
        artifact = str(event.get("rule_id") or event.get("artifact") or "")
        if finding:
            create_or_update_incident(
                INCIDENT_LEDGER,
                finding=finding,
                severity=severity,
                artifact=artifact,
            )

    return path


def _decision_trace_path() -> Path:
    return WORKSPACE_ROOT / "Output" / "governance" / "traces" / "decision_trace.jsonl"


def _audit_force_promotion(run_id: str, force: bool) -> list[dict[str, Any]]:
    if not force:
        return []
    if CONFIG_AUTHORITY_REGISTRY.exists():
        events = audit_config({"force_promoted": True}, CONFIG_AUTHORITY_REGISTRY)
    else:
        events = [
            {
                "config_key": "force_promoted",
                "value": True,
                "event_type": "UNKNOWN_AUTHORITY_CONFIG_ENABLED",
                "severity": "CRITICAL",
                "reason": f"Config authority registry missing at {CONFIG_AUTHORITY_REGISTRY}.",
                "decision_impact": "ACTION_REQUIRED",
            }
        ]
    for event in events:
        record_decision(
            _decision_trace_path(),
            run_id=run_id,
            artifact="force_promoted",
            artifact_type="CONFIG",
            finding=event["event_type"],
            decision_impact=event["decision_impact"],
            consumer="promotion_gate",
            severity=event["severity"],
            reason=event["reason"],
        )
    return cast(list[dict[str, Any]], events)


def _latest_promotion_routing_decision(decisions_dir: Path | None = None) -> tuple[Path | None, dict[str, Any]]:
    decisions_dir = decisions_dir or ROUTING_DECISIONS
    if not decisions_dir.exists():
        return None, {}
    candidates: list[tuple[str, float, Path, dict[str, Any]]] = []
    for path in sorted(decisions_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            print(f"WARNING: Failed to parse routing decision YAML {path}: {exc}", file=sys.stderr)
            continue
        except Exception as exc:
            print(f"WARNING: Failed to read routing decision {path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(payload, dict):
            continue
        decision = payload.get("promotion_gate_decision")
        if not isinstance(decision, dict):
            continue
        timestamp = str(payload.get("timestamp") or payload.get("date") or path.stem)
        candidates.append((timestamp, path.stat().st_mtime, path, payload))
    if not candidates:
        return None, {}
    _, _, path, payload = sorted(candidates, key=lambda item: (item[0], item[1]))[-1]
    return path, payload


def _enforce_routing_decision(run_id: str, snapshot_id: str) -> dict[str, Any]:
    try:
        payload = assert_promotion_allowed(ROUTING_DECISIONS)
    except RoutingGateError as exc:
        decision_path, payload = _latest_promotion_routing_decision()
        gate = payload.get("promotion_gate_decision") if payload else None
        may_promote = gate.get("may_promote_current_snapshot") if isinstance(gate, dict) else None
        decision_id = payload.get("decision_id") or payload.get("task_id") or (decision_path.stem if decision_path else None)
        reason = str(exc)
        _append_system_event(
            {
                "event_type": "snapshot_publish_attempt",
                "severity": "error",
                "tool_id": "scripts.promote_snapshot",
                "mode": "release",
                "decision": "deny",
                "result": "blocked",
                "rule_id": "routing_decision.may_promote_current_snapshot",
                "reason": reason,
                "summary": f"Snapshot promotion blocked: {run_id}",
                "artifacts": [f"Output/deformation_runs/{run_id}"],
                "metadata": {
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "decision_id": decision_id,
                    "decision_path": str(decision_path.relative_to(WORKSPACE_ROOT)) if decision_path else None,
                    "may_promote_current_snapshot": may_promote,
                },
            }
        )
        record_decision(
            _decision_trace_path(),
            run_id=run_id,
            artifact=f"Output/system_learning/routing_decisions/{decision_path.name}" if decision_path else "Output/system_learning/routing_decisions",
            artifact_type="ROUTING_DECISION",
            finding="PROMOTION_BLOCKED",
            decision_impact="BLOCK",
            consumer="promotion_gate",
            severity="HIGH",
            reason=reason,
        )
        write_authority_event(
            AUTHORITY_TRACE,
            run_id=run_id,
            module="promotion_gate",
            operation="routing",
            authority="PROMOTE",
            allowed=False,
            reason=reason,
        )
        raise PromotionError(reason) from exc

    gate = payload.get("promotion_gate_decision", {})
    decision_path_text = payload.get("decision_path")
    decision_path = Path(decision_path_text) if decision_path_text else None
    decision_id = payload.get("decision_id") or payload.get("task_id") or (decision_path.stem if decision_path else None)

    # Check routing decision age
    decision_ts = payload.get("timestamp") or payload.get("date") or ""
    if decision_ts and decision_path:
        try:
            decision_dt = datetime.fromisoformat(str(decision_ts).replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - decision_dt).days
            if age_days > ROUTING_DECISION_MAX_AGE_DAYS:
                reason = f"Routing decision is {age_days} days old (max {ROUTING_DECISION_MAX_AGE_DAYS}). Promotion blocked."
                record_decision(
                    _decision_trace_path(),
                    run_id=run_id,
                    artifact=str(decision_path.relative_to(WORKSPACE_ROOT)) if decision_path.is_relative_to(WORKSPACE_ROOT) else str(decision_path),
                    artifact_type="ROUTING_DECISION",
                    finding="ROUTING_DECISION_EXPIRED",
                    decision_impact="BLOCK",
                    consumer="promotion_gate",
                    severity="HIGH",
                    reason=reason,
                )
                raise PromotionError(reason)
        except (ValueError, TypeError) as exc:
            reason = (
                "Routing decision timestamp could not be parsed "
                f"({type(exc).__name__}); promotion is blocked."
            )
            artifact = (
                str(decision_path.relative_to(WORKSPACE_ROOT))
                if decision_path.is_relative_to(WORKSPACE_ROOT)
                else str(decision_path)
            )
            record_decision(
                _decision_trace_path(),
                run_id=run_id,
                artifact=artifact,
                artifact_type="ROUTING_DECISION",
                finding="ROUTING_DECISION_INVALID_TIMESTAMP",
                decision_impact="BLOCK",
                consumer="promotion_gate",
                severity="HIGH",
                reason=reason,
            )
            write_authority_event(
                AUTHORITY_TRACE,
                run_id=run_id,
                module="promotion_gate",
                operation="routing",
                authority="PROMOTE",
                allowed=False,
                reason=reason,
            )
            raise PromotionError(reason) from exc

    record_decision(
        _decision_trace_path(),
        run_id=run_id,
        artifact=decision_path_text or "Output/system_learning/routing_decisions",
        artifact_type="ROUTING_DECISION",
        finding="PROMOTION_ALLOWED",
        decision_impact="PROMOTE",
        consumer="promotion_gate",
        severity="OK",
        reason=gate.get("reason", "Routing decision allows promotion."),
    )
    write_authority_event(
        AUTHORITY_TRACE,
        run_id=run_id,
        module="promotion_gate",
        operation="routing",
        authority="PROMOTE",
        allowed=True,
        reason=gate.get("reason", "Routing decision allows promotion."),
    )
    if gate.get("may_promote_current_snapshot") is True:
        return {
            "decision_id": decision_id,
            "decision_path": str(decision_path.relative_to(WORKSPACE_ROOT)) if decision_path and decision_path.is_relative_to(WORKSPACE_ROOT) else decision_path_text,
            "may_promote_current_snapshot": True,
        }
    raise PromotionError("Promotion blocked: routing gate returned an invalid allow payload.")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return {str(key): value for key, value in payload.items()}


def _provenance_status(run_dir: Path, manifest: dict) -> dict[str, str]:
    config = _read_json(run_dir / "config_snapshot.json")
    trace_path = run_dir / "traces" / "operator_trace.jsonl"
    trace_status = "missing"
    if trace_path.exists():
        first = trace_path.open().readline()
        trace_status = "missing" if '"status": "missing"' in first else "complete"

    config_status = "missing"
    if config:
        captured = config.get("captured_status")
        if captured == "captured":
            config_status = "complete"
        elif captured == "missing":
            config_status = "reconstructed_post_hoc"
        else:
            config_status = "partial"

    return {
        "run_manifest": "complete" if (run_dir / "run_manifest.json").exists() else "missing",
        "output_manifest": "complete" if (run_dir / "artifacts.json").exists() else "missing",
        "machine_snapshot": "complete" if (run_dir / "machine" / "snapshot.json").exists() else "missing",
        "harvester_release": "complete" if manifest.get("harvester_release") else "missing",
        "config_snapshot": config_status,
        "operator_trace": trace_status,
        "config_hash": "complete" if manifest.get("config_hash") and config_status == "complete" else "partial",
    }


def _known_provenance_limitations(status: dict[str, str]) -> list[str]:
    limitations: list[str] = []
    if status.get("config_snapshot") == "reconstructed_post_hoc":
        limitations.append("config_snapshot.json was not captured at run time; only post-hoc status/hash metadata is available.")
    elif status.get("config_snapshot") == "missing":
        limitations.append("config_snapshot.json is missing.")
    if status.get("operator_trace") == "missing":
        limitations.append("traces/operator_trace.jsonl is missing or contains a missing-status header.")
    if status.get("config_hash") == "partial":
        limitations.append("config hash exists, but it is not backed by a captured runtime config snapshot.")
    return limitations


def main() -> int:
    """CLI entry point — promote or quarantine a deformation snapshot.

    Enforces routing decision, pre-condition checks, report gate, and config
    audit before copying the snapshot to the canonical or quarantine directory.
    """
    parser = argparse.ArgumentParser(
        description="Quarantine or inspect an archived run id. Not a live current promote API."
    )
    parser.add_argument("--run", required=True, help="archived run id (historical evidence only)")
    parser.add_argument("--snapshot-id", default=None, help="defaults to snapshot_<run_id>")
    # nosemgrep: semgrep_rules.force-promotion-without-accountability
    # The runtime gate immediately below requires both accountability fields.
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--authorized-by", default=None, help="REQUIRED when --force: who authorized this override")
    parser.add_argument("--reason", default=None, help="REQUIRED when --force: why the override is necessary")
    parser.add_argument("--scope", default="this_snapshot", help="scope of override (default: this_snapshot)")
    parser.add_argument("--expiry-days", type=int, default=0, help="override expiry in days (0 = single use)")
    args = parser.parse_args()

    if args.force:
        if not args.authorized_by:
            raise SystemExit("--force requires --authorized-by (who authorized this override)")
        if not args.reason:
            raise SystemExit("--force requires --reason (why the override is necessary)")

    run_dir = DEFORMATION_RUNS / args.run
    if not run_dir.exists():
        raise SystemExit(f"run dir does not exist: {run_dir}")
    snapshot_id = args.snapshot_id or f"snapshot_{args.run}"

    routing_decision = _enforce_routing_decision(args.run, snapshot_id)
    manifest, blockers = _check(run_dir, args.force, run_id=args.run)
    blockers.append(
        "Deformation v1 is ARCHIVED_FALSIFIED: canonical promotion is permanently denied; "
        "--force may preserve a copy as non-claim quarantine evidence only."
    )
    authority_config_events = _audit_force_promotion(args.run, args.force)
    provenance_status = _provenance_status(run_dir, manifest)
    known_limitations = _known_provenance_limitations(provenance_status)

    # Report gate connection — fail-closed: corrupt/missing report blocks promotion
    report_verdict = None
    if REPORTS_DIR.exists():
        report_files = sorted(REPORTS_DIR.glob("*.md"))
        if report_files:
            try:
                report_verdict = validate_report_verdict(report_files[-1])
                if report_verdict["verdict"] == "BLOCK":
                    blockers.append(
                        f"Report {report_files[-1].name} verdict is BLOCK: "
                        f"{report_verdict['required_action']} (owner: {report_verdict['owner']})"
                    )
                elif report_verdict["verdict"] in {"ACTION_REQUIRED", "INVESTIGATE"}:
                    blockers.append(
                        f"Report {report_files[-1].name} requires action: {report_verdict['required_action']}"
                    )
            except Exception as exc:
                blockers.append(
                    f"Report {report_files[-1].name} is corrupt or unparseable: {exc}. "
                    "Cannot verify report verdict — promotion blocked."
                )
        else:
            blockers.append(
                "No reports found in Output/reports/. Report gate requires at least one report — promotion blocked."
            )
    else:
        blockers.append(
            "Report directory Output/reports/ missing. Report gate cannot execute — promotion blocked."
        )

    if blockers and not args.force:
        raise PromotionError(
            "Promotion blocked by post-check gates:\n  - "
            + "\n  - ".join(blockers)
            + "\nRe-run with --force to preserve the run as quarantine evidence."
        )

    status = _promotion_status(args.force, blockers)
    target = _snapshot_target(snapshot_id, status)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_dir / "machine" / "snapshot.json", target)

    if CANONICAL_SNAPSHOT_INDEX.exists():
        idx = json.loads(CANONICAL_SNAPSHOT_INDEX.read_text())
    else:
        idx = {"schema_version": "deformation.snapshot_index.v1", "snapshots": []}
    entry = {
        "snapshot_id": snapshot_id,
        "source_run_id": args.run,
        "source_run_path": f"Output/deformation_runs/{args.run}",
        "harvester_release": manifest.get("harvester_release"),
        "snapshot_path": _snapshot_path_text(snapshot_id, status),
        "status": status,
        "promoted_at": _now(),
        "force_promoted": bool(args.force),
        "promotion_blockers": blockers if args.force else [],
        "claim_carrying_allowed": _claim_carrying_allowed(status),
        "config_hash": manifest.get("config_hash"),
        "config_snapshot_status": provenance_status.get("config_snapshot"),
        "output_manifest": f"Output/deformation_runs/{args.run}/artifacts.json",
        "provenance_status": provenance_status,
        "known_provenance_limitations": known_limitations,
        "routing_decision": routing_decision,
        "authority_config_events": authority_config_events,
        "report_verdict": report_verdict,
    }
    if args.force:
        entry["force_authorization"] = {
            "authorized_by": args.authorized_by,
            "reason": args.reason,
            "scope": args.scope,
            "expiry_days": args.expiry_days,
            "authorized_at": _now(),
        }
    _write_snapshot_index(idx, entry)

    manifest.setdefault("promotion", {})
    manifest["promotion"]["snapshot_promoted"] = status == "canonical"
    manifest["promotion"]["snapshot_status"] = status
    manifest["promotion"]["claim_carrying_allowed"] = _claim_carrying_allowed(status)
    manifest["promotion"]["canonical_snapshot_id"] = snapshot_id if status == "canonical" else None
    manifest["promotion"]["quarantine_snapshot_id"] = snapshot_id if status != "canonical" else None
    manifest["promotion"]["promoted_at"] = _now()
    manifest["promotion"]["force_promoted"] = bool(args.force)
    manifest["promotion"]["promotion_blockers"] = blockers if args.force else []
    manifest["promotion"]["provenance_status"] = provenance_status
    manifest["promotion"]["known_provenance_limitations"] = known_limitations
    manifest["promotion"]["routing_decision"] = routing_decision
    manifest["promotion"]["authority_config_events"] = authority_config_events
    if args.force:
        manifest["promotion"]["force_authorization"] = {
            "authorized_by": args.authorized_by,
            "reason": args.reason,
            "scope": args.scope,
        }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    action = "Promoted" if status == "canonical" else "Quarantined"
    print(f"{action} {args.run} -> {target.relative_to(WORKSPACE_ROOT)}")
    if args.force and blockers:
        _append_system_event(
            {
                "event_type": "force_promotion_quarantined",
                "severity": "HIGH",
                "tool_id": "scripts.promote_snapshot",
                "mode": "release",
                "decision": "quarantine",
                "result": "warning",
                "rule_id": "force_promotion_quarantine",
                "reason": f"Force promotion by {args.authorized_by}: {args.reason}",
                "summary": f"Forced run preserved as non-claim quarantine evidence after {len(blockers)} blocker(s)",
                "artifacts": [f"Output/deformation_runs/{args.run}"],
                "metadata": {
                    "run_id": args.run,
                    "snapshot_id": snapshot_id,
                    "snapshot_status": status,
                    "claim_carrying_allowed": False,
                    "authorized_by": args.authorized_by,
                    "blocker_count": len(blockers),
                    "blockers": blockers,
                },
            }
        )
        write_authority_event(
            AUTHORITY_TRACE,
            run_id=args.run,
            module="promotion_gate",
            operation="force_promote",
            authority="PROMOTE",
            allowed=False,
            reason=f"Force promotion by {args.authorized_by} preserved only as quarantine evidence: {args.reason}",
        )

    print("Rebuilding system index...")
    from .build_system_index import build

    build()
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except PromotionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        rc = 1
    raise SystemExit(rc)


if __name__ == "__main__":
    raise SystemExit(main())
