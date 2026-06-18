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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _latest_run_dir(root: Path) -> Path | None:
    pointer = root / "Output" / "current" / "latest_run_id.txt"
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


def _gate_status(root: Path) -> dict[str, Any]:
    promotion = _load_json(root / "Output" / "judgment" / "promotion_gate.json") or {}
    risk = _load_json(root / "Output" / "trade_decision" / "risk_gate.json") or {}

    promotion_status = promotion.get("overall_status", "NO_DATA")
    blocked = promotion.get("blocked_gates", []) or []
    watch = promotion.get("watch_gates", []) or []
    can_enter_current = promotion_status in {"PASS", "WATCH"} and not blocked
    can_affect_core = promotion_status == "PASS" and not blocked

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
        "can_affect_trade_decision": can_affect_trade,
    }


def _contract_status(root: Path) -> dict[str, Any]:
    supervisor = _load_json(root / "Output" / "system_learning" / "latest" / "supervisor_check.json") or {}
    architecture = _load_json(root / "Output" / "system_learning" / "latest" / "architecture_reality_audit.json") or {}
    routing = _load_json(root / "Output" / "system_learning" / "latest" / "output_routing_report.json") or {}

    arch_summary = architecture.get("summary", {}) if isinstance(architecture, dict) else {}
    routing_summary = routing.get("summary", {}) if isinstance(routing, dict) else {}

    return {
        "supervisor_status": supervisor.get("overall_status", "NO_DATA"),
        "supervisor_review_items": len(supervisor.get("review_queue", []) or []),
        "architecture_status": arch_summary.get("overall_status", "NO_DATA"),
        "architecture_findings": arch_summary.get("total_findings", 0),
        "output_routing_status": routing_summary.get("overall_status", "NO_DATA"),
        "output_routing_findings": routing_summary.get("total_findings", 0),
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
        if age_days is not None and age_days > max_age:
            overdue_items.append(entry)

    return {
        "status": "WATCH" if open_items else "PASS",
        "open_count": len(open_items),
        "overdue_count": len(overdue_items),
        "max_open_age_days": max_age,
        "open_items": open_items,
        "overdue_items": overdue_items,
    }


def _incentive_status(root: Path, gates: dict[str, Any], run_trace: dict[str, Any]) -> dict[str, Any]:
    policy = _load_yaml(root / "governance" / "incentive_policy.yaml") or {}
    credits: list[str] = []

    if run_trace.get("trace_complete"):
        credits.extend(["registration", "provenance"])
    if gates.get("can_enter_current"):
        credits.append("consumed_by_module")
    if gates.get("can_affect_core_judgment"):
        credits.append("stable_consumption")

    if gates.get("can_affect_core_judgment") and run_trace.get("trace_complete"):
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
        "can_enter_current": bool(level.get("can_enter_current", False)),
        "can_affect_core_judgment": bool(level.get("can_affect_core_judgment", False)),
        "next_review_hint": _review_hint(tier, gates, run_trace),
    }


def _review_hint(tier: str, gates: dict[str, Any], run_trace: dict[str, Any]) -> str:
    if tier == "canonical":
        return "Maintain passing gates and trace completeness."
    if not run_trace.get("trace_complete"):
        return "Complete run manifest, step log, artifact index, and decision/signal trace."
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
) -> str:
    hard_contract_states = {contracts.get("supervisor_status"), contracts.get("architecture_status")}
    if gates.get("promotion_gate") == "BLOCKED" or gates.get("blocked_gates"):
        return "BLOCKED"
    if "OVERDUE" in hard_contract_states or "INCOMPLETE" in hard_contract_states:
        return "BLOCKED"
    if run_trace.get("status") == "MISSING":
        return "BLOCKED"
    if (
        gates.get("promotion_gate") == "WATCH"
        or contracts.get("architecture_findings", 0)
        or contracts.get("output_routing_findings", 0)
        or exceptions.get("open_count", 0)
        or run_trace.get("status") == "WARN"
    ):
        return "WATCH"
    return "PASS"


def _review_queue(
    run_trace: dict[str, Any],
    gates: dict[str, Any],
    contracts: dict[str, Any],
    exceptions: dict[str, Any],
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
    for item in exceptions.get("overdue_items", []):
        queue.append({
            "source": "experimental_submission",
            "severity": "medium",
            "action": f"{item['id']} exceeds review age limit.",
        })
    return queue


def run_governance_status(root: Path = ROOT) -> dict[str, Any]:
    run_trace = _run_trace_status(root)
    gates = _gate_status(root)
    contracts = _contract_status(root)
    exceptions = _exception_status(root)
    incentive = _incentive_status(root, gates, run_trace)
    overall = _overall_status(run_trace, gates, contracts, exceptions)
    queue = _review_queue(run_trace, gates, contracts, exceptions)

    return {
        "schema_version": "system.governance_status.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "run_trace": run_trace,
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
        f"- Can affect trade decision: {gates['can_affect_trade_decision']}",
        f"- Claim ceiling: {gates['claim_ceiling']}",
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
        "Generated by scripts/governance_status.py.",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any], root: Path = ROOT) -> dict[str, str]:
    output_dir = root / "Output" / "system_learning" / "latest"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "governance_status.json"
    md_path = output_dir / "governance_status.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(generate_markdown(report), encoding="utf-8")
    return {
        "json": str(json_path.relative_to(root)),
        "markdown": str(md_path.relative_to(root)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build governance status summary.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = run_governance_status(ROOT)
    paths = write_outputs(report, ROOT)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Governance status: {report['overall_status']}")
        print(f"Review status: {report['incentive']['review_status']}")
        print(f"Can affect core judgment: {report['gates']['can_affect_core_judgment']}")
        print(f"Report: {paths['markdown']}")


if __name__ == "__main__":
    main()
