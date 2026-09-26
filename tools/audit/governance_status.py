#!/usr/bin/env python3
"""Governance status - visible summary for the default work path.

This script turns scattered governance outputs into one machine-readable
surface. It does not approve work. It reports which layer the latest run is
allowed to occupy: existing, current readout, core judgment, or trade action.

Outputs:
    Output/system_learning/latest/governance_status.json
    Output/system_learning/latest/governance_status.md
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verity.runtime._authority_graph import (  # noqa: E402
    build_authority_graph,
    completed_steps_from_run,
    graph_credit_metrics,
    runtime_can_affect_core_judgment,
    write_authority_graph,
)
from verity.runtime.runtime_io import (  # noqa: E402
    ROOT,
    ensure_dir,
    surface_dir,
    write_json,
)
from verity.runtime.runtime_io import load_json as _load_json
from verity.runtime.runtime_io import load_yaml as _load_yaml

OUTPUT_DIR = surface_dir("system_learning") / "latest"
CONTRACT_REPORT_TTL_HOURS = 168
CONTRACT_REPORT_CADENCE = "weekly"


def _surface(root: Path, name: str) -> Path:
    return surface_dir(name) if root == ROOT else root / "Output" / name


def _latest_run_dir(root: Path) -> Path | None:
    pointer = _surface(root, "current") / "latest_run_id.txt"
    if not pointer.exists():
        return None
    run_id = pointer.read_text(encoding="utf-8").strip()
    if not run_id:
        return None
    run_dir = root / "Output" / "runs" / run_id
    return run_dir if run_dir.exists() else None


def _run_trace_status(root: Path) -> dict[str, Any]:
    run_dir = _latest_run_dir(root)
    if not run_dir:
        return {
            "status": "MISSING",
            "run_id": None,
            "trace_complete": False,
            "missing": ["latest_run_dir"],
        }

    required = ["manifest.json", "input_snapshot.json", "steps.jsonl", "artifact_index.json"]
    missing = [name for name in required if not (run_dir / name).exists()]
    manifest = _load_json(run_dir / "manifest.json") or {}
    has_trace = (run_dir / "decision_trace.json").exists() or (run_dir / "signal_trace.json").exists()
    if not has_trace:
        missing.append("decision_or_signal_trace")

    return {
        "status": "PASS" if not missing else "WARN",
        "run_id": manifest.get("run_id", run_dir.name),
        "mode": manifest.get("mode", "unknown"),
        "run_status": manifest.get("status", "unknown"),
        "steps_count": manifest.get("steps_count", 0),
        "steps_failed": manifest.get("steps_failed", 0),
        "trace_complete": not missing,
        "run_dir": str(run_dir.relative_to(root)),
        "missing": missing,
    }


def _authority_graph_status(root: Path, run_trace: dict[str, Any]) -> dict[str, Any]:
    graph = build_authority_graph(root)
    write_authority_graph(graph, root)
    completed = completed_steps_from_run(root)
    promotion_pass = False  # filled by caller when composing gates
    return {
        "graph": graph,
        "completed_steps": sorted(completed),
        "metrics": graph.get("metrics", {}),
        "invariants_valid": bool(graph.get("invariants", {}).get("valid", False)),
        "drift_count": graph.get("metrics", {}).get("drift_count", 0),
        "violation_count": len(graph.get("invariants", {}).get("violations", [])),
        "promotion_pass": promotion_pass,
        "trace_complete": bool(run_trace.get("trace_complete")),
    }


def _gate_status(root: Path, authority_graph: dict[str, Any], run_trace: dict[str, Any]) -> dict[str, Any]:
    promotion = _load_json(_surface(root, "judgment") / "promotion_gate.json") or {}
    risk = _load_json(_surface(root, "trade_decision") / "risk_gate.json") or {}

    promotion_status = promotion.get("overall_status", "NO_DATA")
    blocked = promotion.get("blocked_gates", []) or []
    watch = promotion.get("watch_gates", []) or []
    can_enter_current = promotion_status in {"PASS", "WATCH"} and not blocked
    promotion_pass = promotion_status == "PASS" and not blocked
    can_affect_core = promotion_pass

    graph = authority_graph.get("graph", {})
    completed = set(authority_graph.get("completed_steps", []))
    topology = runtime_can_affect_core_judgment(
        graph,
        promotion_gate_pass=promotion_pass,
        trace_complete=bool(run_trace.get("trace_complete")),
        completed_steps=completed,
    )

    allowed_actions = risk.get("allowed_actions", {}) if isinstance(risk, dict) else {}
    can_affect_trade = bool(allowed_actions.get("live_execution", False))

    return {
        "promotion_gate": promotion_status,
        "claim_ceiling": promotion.get("claim_ceiling", "unknown"),
        "blocked_gates": blocked,
        "watch_gates": watch,
        "blocking_reasons": promotion.get("blocking_reasons", []) or [],
        "watch_reasons": promotion.get("watch_reasons", []) or [],
        "allowed_language": promotion.get("allowed_language", []) or [],
        "forbidden_language": promotion.get("forbidden_language", []) or [],
        "risk_gate": (risk.get("risk_check") or {}).get("status", "NO_DATA"),
        "can_enter_current": can_enter_current,
        "can_affect_core_judgment": can_affect_core,
        "topology_bounded_core_judgment": topology.get("allowed", False),
        "effective_can_affect_core_judgment": can_affect_core and topology.get("allowed", False),
        "topology_blocking_reasons": topology.get("blocking_reasons", []),
        "can_affect_trade_decision": can_affect_trade,
    }


def _parse_report_time(payload: dict[str, Any], path: Path) -> tuple[datetime | None, str]:
    for key in ("generated_at", "timestamp", "audit_timestamp"):
        raw = payload.get(key)
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC), key
    return None, "content_clock_missing" if path.exists() else "missing"


def _load_contract_report(
    path: Path,
    *,
    now: datetime,
    ttl_hours: int = CONTRACT_REPORT_TTL_HOURS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _load_json(path) or {}
    report_time, clock_source = _parse_report_time(payload, path)
    age_hours = None
    if report_time is not None:
        age_hours = max(0.0, (now - report_time).total_seconds() / 3600)
    if not path.exists() or not payload:
        freshness_status = "MISSING"
    elif age_hours is None:
        freshness_status = "NO_CONTENT_CLOCK"
    elif age_hours > ttl_hours:
        freshness_status = "STALE"
    else:
        freshness_status = "FRESH"
    freshness = {
        "path": str(path),
        "status": freshness_status,
        "generated_at": report_time.isoformat() if report_time else None,
        "clock_source": clock_source,
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "ttl_hours": ttl_hours,
        "cadence": payload.get("cadence"),
        "source_run_id": payload.get("run_id") or payload.get("source_run_id"),
        "source_sha": payload.get("source_sha") or payload.get("git_sha"),
    }
    return payload, freshness


def _contract_status(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    checked_at = now or datetime.now(UTC)
    expected_run_id = os.environ.get("ZCODE_BUNDLE_RUN_ID")
    latest = _surface(root, "system_learning") / "latest"
    supervisor, supervisor_freshness = _load_contract_report(
        latest / "supervisor_check.json", now=checked_at
    )
    architecture, architecture_freshness = _load_contract_report(
        latest / "architecture_reality_audit.json", now=checked_at
    )
    routing, routing_freshness = _load_contract_report(
        latest / "output_routing_report.json", now=checked_at
    )

    arch_summary = architecture.get("summary", {}) if isinstance(architecture, dict) else {}
    routing_summary = routing.get("summary", {}) if isinstance(routing, dict) else {}
    freshness = {
        "supervisor": supervisor_freshness,
        "architecture_reality": architecture_freshness,
        "output_routing": routing_freshness,
    }
    if expected_run_id:
        for item in freshness.values():
            item["expected_run_id"] = expected_run_id
            item["same_run"] = item.get("source_run_id") == expected_run_id
            if item["status"] == "FRESH" and not item["same_run"]:
                item["status"] = "RUN_MISMATCH"
    for item in freshness.values():
        item["expected_cadence"] = CONTRACT_REPORT_CADENCE
        item["same_cadence"] = item.get("cadence") == CONTRACT_REPORT_CADENCE
        if item["status"] == "FRESH" and not item["same_cadence"]:
            item["status"] = (
                "CADENCE_UNDECLARED"
                if not item.get("cadence")
                else "CADENCE_MISMATCH"
            )

    def effective_status(raw_status: str, report_freshness: dict[str, Any]) -> str:
        state = report_freshness["status"]
        return raw_status if state == "FRESH" else state

    return {
        "supervisor_status": effective_status(
            supervisor.get("overall_status", "NO_DATA"), supervisor_freshness
        ),
        "supervisor_review_items": len(supervisor.get("review_queue", []) or []),
        "architecture_status": effective_status(
            arch_summary.get("overall_status", "NO_DATA"), architecture_freshness
        ),
        "architecture_findings": arch_summary.get("total_findings", 0),
        "output_routing_status": effective_status(
            routing_summary.get("overall_status", "NO_DATA"), routing_freshness
        ),
        "output_routing_findings": routing_summary.get("total_findings", 0),
        "freshness": freshness,
        "stale_or_missing_count": sum(
            item["status"] != "FRESH" for item in freshness.values()
        ),
    }


def _exception_status(root: Path) -> dict[str, Any]:
    registry = _load_yaml(root / "governance" / "experimental_submission_registry.yaml") or {}
    submissions = registry.get("submissions", []) or []
    schedule = registry.get("review_schedule", {}) or {}
    max_age = int(schedule.get("max_open_age_days", 14))
    today = datetime.now(UTC).date()

    open_statuses = {"submitted", "pending", "open", "reviewing", "accepted_as_research"}
    open_items = []
    overdue_items = []
    topology_review_items = []
    for item in submissions:
        status = str(item.get("status", "submitted"))
        if status not in open_statuses:
            continue
        date_raw = str(item.get("date") or item.get("submitted_at") or "")[:10]
        age_days = None
        if date_raw:
            try:
                age_days = (today - datetime.fromisoformat(date_raw).date()).days
            except ValueError:
                age_days = None
        entry = {
            "id": item.get("submission_id", "unknown"),
            "status": status,
            "priority": item.get("current_priority", "low"),
            "review_deadline": item.get("review_deadline"),
            "age_days": age_days,
        }
        open_items.append(entry)
        if str(item.get("submission_type", "")) == "topology_change":
            topology_review_items.append(entry)
        if age_days is not None and age_days > max_age:
            overdue_items.append(entry)

    return {
        "status": "WATCH" if open_items else "PASS",
        "open_count": len(open_items),
        "overdue_count": len(overdue_items),
        "topology_review_count": len(topology_review_items),
        "max_open_age_days": max_age,
        "open_items": open_items,
        "overdue_items": overdue_items,
        "topology_review_items": topology_review_items,
    }


def _incentive_status(
    root: Path,
    gates: dict[str, Any],
    run_trace: dict[str, Any],
    authority_graph: dict[str, Any],
) -> dict[str, Any]:
    policy = _load_yaml(root / "governance" / "incentive_policy.yaml") or {}
    credits: list[str] = []
    graph_metrics = graph_credit_metrics(
        authority_graph.get("graph", {}),
        set(authority_graph.get("completed_steps", [])),
    )

    if run_trace.get("trace_complete"):
        credits.extend(["registration", "provenance"])
    if gates.get("can_enter_current"):
        credits.append("consumed_by_module")
    if graph_metrics.get("total_in_degree", 0) > 0:
        credits.append("graph_in_degree")
    if graph_metrics.get("core_capable_completed", 0) > 0:
        credits.append("graph_core_path")
    if gates.get("effective_can_affect_core_judgment"):
        credits.append("stable_consumption")

    if gates.get("effective_can_affect_core_judgment") and run_trace.get("trace_complete"):
        tier = "canonical"
    elif gates.get("can_enter_current"):
        tier = "preferred"
    elif run_trace.get("trace_complete"):
        tier = "registered"
    else:
        tier = "low"

    levels = policy.get("priority_levels", {})
    level = levels.get(tier, {})
    return {
        "review_status": tier,
        "meaning": level.get("meaning", ""),
        "credits_active": credits,
        "graph_metrics": graph_metrics,
        "can_enter_current": bool(level.get("can_enter_current", False)),
        "can_affect_core_judgment": bool(level.get("can_affect_core_judgment", False)),
        "next_review_hint": _review_hint(tier, gates, run_trace),
    }


def _review_hint(tier: str, gates: dict[str, Any], run_trace: dict[str, Any]) -> str:
    if tier == "canonical":
        return "Maintain passing gates, topology invariants, and trace completeness."
    if not run_trace.get("trace_complete"):
        return "Complete run manifest, step log, artifact index, and decision/signal trace."
    if gates.get("topology_blocking_reasons"):
        return (
            "Resolve topology blockers: "
            + ", ".join(gates["topology_blocking_reasons"])
        )
    if gates.get("promotion_gate") == "WATCH":
        return "Resolve watch gates before core judgment authority is allowed."
    if gates.get("promotion_gate") == "BLOCKED":
        return "Resolve blocked gates before entering current readout."
    return "Add downstream consumption and stable passing runs."


def _overall_status(
    run_trace: dict[str, Any],
    gates: dict[str, Any],
    contracts: dict[str, Any],
    exceptions: dict[str, Any],
    authority_graph: dict[str, Any],
) -> str:
    hard_contract_states = {contracts.get("supervisor_status"), contracts.get("architecture_status")}
    if gates.get("promotion_gate") == "BLOCKED" or gates.get("blocked_gates"):
        return "BLOCKED"
    if hard_contract_states & {
        "OVERDUE",
        "INCOMPLETE",
        "STALE",
        "MISSING",
        "NO_CONTENT_CLOCK",
        "RUN_MISMATCH",
        "CADENCE_UNDECLARED",
        "CADENCE_MISMATCH",
    }:
        return "BLOCKED"
    if run_trace.get("status") == "MISSING":
        return "BLOCKED"
    if (
        gates.get("promotion_gate") == "WATCH"
        or contracts.get("architecture_findings", 0)
        or contracts.get("output_routing_findings", 0)
        or contracts.get("output_routing_status")
        in {"STALE", "MISSING", "NO_CONTENT_CLOCK", "RUN_MISMATCH"}
        or exceptions.get("open_count", 0)
        or authority_graph.get("drift_count", 0)
        or not authority_graph.get("invariants_valid", True)
        or run_trace.get("status") == "WARN"
    ):
        return "WATCH"
    return "PASS"


def _review_queue(
    run_trace: dict[str, Any],
    gates: dict[str, Any],
    contracts: dict[str, Any],
    exceptions: dict[str, Any],
    authority_graph: dict[str, Any],
) -> list[dict[str, str]]:
    queue: list[dict[str, str]] = []
    for reason in gates.get("blocking_reasons", []):
        queue.append({"source": "promotion_gate", "severity": "high", "action": str(reason)})
    for reason in gates.get("watch_reasons", []):
        queue.append({"source": "promotion_gate", "severity": "medium", "action": str(reason)})
    if run_trace.get("missing"):
        queue.append({
            "source": "run_bundle",
            "severity": "medium",
            "action": "Missing trace artifacts: " + ", ".join(run_trace["missing"]),
        })
    if contracts.get("architecture_findings", 0):
        queue.append({
            "source": "architecture_reality_audit",
            "severity": "medium",
            "action": f"{contracts['architecture_findings']} architecture finding(s) need review.",
        })
    if contracts.get("output_routing_findings", 0):
        queue.append({
            "source": "output_routing_policy",
            "severity": "medium",
            "action": f"{contracts['output_routing_findings']} output routing finding(s) need review.",
        })
    for name, freshness in contracts.get("freshness", {}).items():
        if freshness.get("status") == "FRESH":
            continue
        queue.append({
            "source": name,
            "severity": "high" if name in {"supervisor", "architecture_reality"} else "medium",
            "action": (
                f"Contract report is {freshness.get('status')}; "
                f"age={freshness.get('age_hours')}h, ttl={freshness.get('ttl_hours')}h."
            ),
        })
    for item in exceptions.get("overdue_items", []):
        queue.append({
            "source": "experimental_submission",
            "severity": "medium",
            "action": f"{item['id']} exceeds review age limit.",
        })
    for reason in gates.get("topology_blocking_reasons", []):
        queue.append({
            "source": "authority_graph",
            "severity": "medium",
            "action": str(reason),
        })
    graph = authority_graph.get("graph", {})
    for violation in graph.get("invariants", {}).get("violations", []):
        if violation.get("severity") == "high":
            queue.append({
                "source": "authority_graph",
                "severity": "high",
                "action": str(violation.get("message", violation.get("id"))),
            })
    for item in exceptions.get("topology_review_items", []):
        queue.append({
            "source": "topology_change",
            "severity": "high",
            "action": f"{item['id']} proposes authority graph change.",
        })
    return queue


def _authority_graph_summary(authority_graph: dict[str, Any]) -> dict[str, Any]:
    graph = authority_graph.get("graph", {})
    return {
        "path": "Output/system_learning/latest/authority_graph.json",
        "invariants_valid": authority_graph.get("invariants_valid", False),
        "drift_count": authority_graph.get("drift_count", 0),
        "exempt_drift_count": graph.get("metrics", {}).get("exempt_drift_count", 0),
        "violation_count": authority_graph.get("violation_count", 0),
        "core_capable_step_count": graph.get("metrics", {}).get("core_capable_step_count", 0),
        "completed_steps": authority_graph.get("completed_steps", []),
    }


def run_governance_status(root: Path = ROOT) -> dict[str, Any]:
    run_trace = _run_trace_status(root)
    authority_graph = _authority_graph_status(root, run_trace)
    gates = _gate_status(root, authority_graph, run_trace)
    contracts = _contract_status(root)
    exceptions = _exception_status(root)
    incentive = _incentive_status(root, gates, run_trace, authority_graph)
    overall = _overall_status(run_trace, gates, contracts, exceptions, authority_graph)
    queue = _review_queue(run_trace, gates, contracts, exceptions, authority_graph)

    return {
        "schema_version": "system.governance_status.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "cadence": CONTRACT_REPORT_CADENCE,
        "source_run_id": os.environ.get("ZCODE_BUNDLE_RUN_ID"),
        "overall_status": overall,
        "run_trace": run_trace,
        "authority_graph": _authority_graph_summary(authority_graph),
        "gates": gates,
        "contracts": contracts,
        "exceptions": exceptions,
        "incentive": incentive,
        "review_queue": queue,
    }


def generate_markdown(report: dict[str, Any]) -> str:
    gates = report["gates"]
    run_trace = report["run_trace"]
    contracts = report["contracts"]
    exceptions = report["exceptions"]
    incentive = report["incentive"]

    lines = [
        "# Governance Status",
        "",
        f"Generated: {report['generated_at']}",
        f"Overall status: {report['overall_status']}",
        "",
        "## Boundary Status",
        "",
        f"- Review status: {incentive['review_status']}",
        f"- Can enter current: {gates['can_enter_current']}",
        f"- Can affect core judgment: {gates['can_affect_core_judgment']}",
        f"- Topology-bounded core judgment: {gates.get('topology_bounded_core_judgment', False)}",
        f"- Effective core judgment: {gates.get('effective_can_affect_core_judgment', False)}",
        f"- Can affect trade decision: {gates['can_affect_trade_decision']}",
        f"- Claim ceiling: {gates['claim_ceiling']}",
        "",
        "## Authority Graph",
        "",
        f"- Invariants valid: {report.get('authority_graph', {}).get('invariants_valid')}",
        f"- Declared/derived drift: {report.get('authority_graph', {}).get('drift_count')}",
        f"- Exempt assembly drift: {report.get('authority_graph', {}).get('exempt_drift_count', 0)}",
        f"- Core-capable steps: {report.get('authority_graph', {}).get('core_capable_step_count')}",
        "",
        "## Default Path Trace",
        "",
        f"- Run ID: {run_trace.get('run_id')}",
        f"- Mode: {run_trace.get('mode')}",
        f"- Run status: {run_trace.get('run_status')}",
        f"- Trace complete: {run_trace.get('trace_complete')}",
        "",
        "## Gates",
        "",
        f"- Promotion gate: {gates['promotion_gate']}",
        f"- Risk gate: {gates['risk_gate']}",
        f"- Blocked gates: {', '.join(gates['blocked_gates']) or 'none'}",
        f"- Watch gates: {', '.join(gates['watch_gates']) or 'none'}",
        "",
        "## Contracts",
        "",
        f"- Supervisor: {contracts['supervisor_status']}",
        f"- Architecture reality: {contracts['architecture_status']} ({contracts['architecture_findings']} findings)",
        f"- Output routing: {contracts['output_routing_status']} ({contracts['output_routing_findings']} findings)",
        f"- Expected report cadence: {CONTRACT_REPORT_CADENCE}",
        f"- Stale or missing contract reports: {contracts.get('stale_or_missing_count', 0)}",
        "",
        "## Exceptions",
        "",
        f"- Open experimental submissions: {exceptions['open_count']}",
        f"- Overdue experimental submissions: {exceptions['overdue_count']}",
        "",
        "## Review Queue",
        "",
    ]
    if report["review_queue"]:
        for item in report["review_queue"]:
            lines.append(f"- [{item['severity']}] {item['source']}: {item['action']}")
    else:
        lines.append("- No review items.")

    lines += [
        "",
        "## Next Review Hint",
        "",
        incentive["next_review_hint"],
        "",
        "---",
        "",
        "Generated by scripts/commands/weekly/governance_status.py.",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], root: Path = ROOT) -> dict[str, str]:
    output_dir = _surface(root, "system_learning") / "latest"
    ensure_dir(output_dir)
    json_path = output_dir / "governance_status.json"
    md_path = output_dir / "governance_status.md"
    write_json(json_path, report)
    md_path.write_text(generate_markdown(report), encoding="utf-8")
    return {
        "json": str(json_path.relative_to(root)),
        "markdown": str(md_path.relative_to(root)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build governance status summary.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument(
        "--exceptions-only",
        action="store_true",
        help="Write full artifacts but print only non-healthy status deviations.",
    )
    args = parser.parse_args()

    report = run_governance_status(ROOT)
    paths = write_outputs(report, ROOT)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.exceptions_only:
        deviations = []
        if report["overall_status"] not in {"PASS", "HEALTHY", "OK"}:
            deviations.append(f"governance={report['overall_status']}")
        if not report["gates"]["can_affect_core_judgment"]:
            deviations.append("core_judgment=blocked")
        if deviations:
            print("; ".join(deviations))
            print(f"evidence={paths['markdown']}")
    else:
        print(f"Governance status: {report['overall_status']}")
        print(f"Review status: {report['incentive']['review_status']}")
        print(f"Can affect core judgment: {report['gates']['can_affect_core_judgment']}")
        print(f"Report: {paths['markdown']}")


if __name__ == "__main__":
    main()
