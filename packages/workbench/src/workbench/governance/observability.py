from __future__ import annotations

from pathlib import Path
from typing import Any

from .incident import incident_summary_rows
from .report_gate import validate_report_verdict
from .routing_gate import RoutingGateError, assert_promotion_allowed, latest_routing_decision, load_routing_decision, promotion_gate_payload
from .semantic import SemanticRegistry
from .trace_summary import summarize_trace_paths


def semantic_risk_rows(registry: SemanticRegistry) -> list[dict[str, Any]]:
    """Build semantic risk summary rows from the registry for dashboard display."""
    rows: list[dict[str, Any]] = []
    for concept, meta in registry.data.items():
        distance = meta.get("semantic_distance")
        status = meta.get("proxy_status")
        if meta.get("implemented_status") == "NOT_IMPLEMENTED":
            verdict = "unsupported"
        elif distance is not None and distance >= 4:
            verdict = "cannot support strong structural claim"
        elif distance is not None and distance >= 3:
            verdict = "use as partial only"
        else:
            verdict = "low semantic risk"
        rows.append(
            {
                "concept": concept,
                "status": status,
                "distance": "N/A" if distance is None else distance,
                "verdict": verdict,
            }
        )
    return rows


def promotion_gate_status(routing_dir: str | Path) -> dict[str, Any]:
    """Check promotion gate status without raising — returns a status dict with ALLOWED/BLOCKED."""
    latest = latest_routing_decision(routing_dir)
    if latest is None:
        return {
            "routing_decision_found": False,
            "may_promote_current_snapshot": None,
            "promotion_result": "BLOCKED",
            "reason": f"No routing decision found in {routing_dir}",
        }
    decision = load_routing_decision(latest)
    gate = promotion_gate_payload(decision)
    try:
        assert_promotion_allowed(routing_dir)
    except RoutingGateError as exc:
        return {
            "routing_decision_found": True,
            "may_promote_current_snapshot": gate.get("may_promote_current_snapshot"),
            "promotion_result": "BLOCKED",
            "reason": str(exc),
            "decision_path": str(latest),
        }
    return {
        "routing_decision_found": True,
        "may_promote_current_snapshot": True,
        "promotion_result": "ALLOWED",
        "reason": gate.get("reason", "Routing decision allows promotion."),
        "decision_path": str(latest),
    }


def render_run_observability_summary(
    *,
    run_id: str,
    semantic_registry_path: str | Path,
    decision_trace_path: str | Path,
    authority_trace_path: str | Path,
    routing_dir: str | Path,
    incident_ledger_path: str | Path | None = None,
    reports_dir: str | Path | None = None,
) -> str:
    """Render a full run observability summary as Markdown.

    Aggregates authority traces, decision impacts, recurring findings,
    incidents, semantic risk, report gate, and promotion gate into a single
    actionable summary with an Actionable Verdict section.
    """
    trace_summary = summarize_trace_paths(
        decision_trace_path=decision_trace_path,
        authority_trace_path=authority_trace_path,
    )
    semantic_rows = semantic_risk_rows(SemanticRegistry(semantic_registry_path))
    promotion = promotion_gate_status(routing_dir)
    decision_counts = trace_summary["decision_impact_counts"]
    authority = trace_summary["authority"]
    recurring = trace_summary.get("recurring_findings", [])
    verdict = "PROMOTE" if promotion["promotion_result"] == "ALLOWED" and decision_counts["BLOCK"] == 0 else "BLOCK"
    severity = "HIGH" if verdict == "BLOCK" else "LOW"

    # Report gate check
    report_status = "UNKNOWN"
    report_verdict = "UNKNOWN"
    report_path_text = "NONE"
    if reports_dir:
        reports_dir = Path(reports_dir)
        if reports_dir.exists():
            report_files = sorted(reports_dir.glob("*.md"))
            if report_files:
                try:
                    result = validate_report_verdict(report_files[-1])
                    report_verdict = result["verdict"]
                    report_status = "CHECKED"
                    report_path_text = str(report_files[-1].relative_to(reports_dir))
                    if report_verdict == "BLOCK":
                        verdict = "BLOCK"
                        severity = "CRITICAL"
                except Exception:
                    report_status = "INVALID"

    # Incident summary
    incident_rows: list[dict[str, Any]] = []
    if incident_ledger_path:
        incident_rows = incident_summary_rows(incident_ledger_path)
    open_incidents = sum(1 for r in incident_rows if r["status"] == "OPEN")
    critical_incidents = sum(1 for r in incident_rows if r["severity"] == "CRITICAL")
    if critical_incidents > 0:
        verdict = "BLOCK"
        severity = "CRITICAL"

    lines = [
        "# Run Observability Summary",
        f"Run ID: {run_id}",
        "",
        "## 1. Authority",
        f"- Authority violations: {authority['authority_violations']}",
        f"- Authority configs enabled: {authority['authority_configs_enabled']}",
        "- Legacy fallback used: UNKNOWN",
        "",
        "## 2. Decision Impact",
        "| Impact | Count |",
        "|---|---:|",
    ]
    for impact, count in decision_counts.items():
        lines.append(f"| {impact} | {count} |")
    lines += [
        "",
        "## 3. Recurring Findings",
    ]
    if recurring:
        lines.append("| Finding | Artifact | Count | Severity |")
        lines.append("|---|---:|---|")
        for r in recurring:
            lines.append(f"| {r['finding_type']} | {r['artifact']} | {r['occurrence_count']} | {r['severity']} |")
    else:
        lines.append("No recurring findings detected.")
    lines += [
        "",
        "## 4. Incidents",
    ]
    if incident_rows:
        lines.append("| Finding | Severity | Count | Status | Last Seen |")
        lines.append("|---|---:|---|---|")
        for r in incident_rows:
            lines.append(f"| {r['finding_type'][:60]} | {r['severity']} | {r['occurrence_count']} | {r['status']} | {r['last_seen']} |")
        lines.append(f"\nOpen incidents: {open_incidents} | Critical: {critical_incidents}")
    else:
        lines.append("No open incidents.")
    lines += [
        "",
        "## 5. Semantic Risk",
        "| Concept | Status | Distance | Verdict |",
        "|---|---|---:|---|",
    ]
    for row in semantic_rows:
        lines.append(f"| {row['concept']} | {row['status']} | {row['distance']} | {row['verdict']} |")
    lines += [
        "",
        "## 6. Report Gate",
        f"- Reports checked: {report_status}",
        f"- Report path: {report_path_text}",
        f"- Report verdict: {report_verdict}",
        "",
        "## 7. Promotion Gate",
        f"- Routing decision found: {'YES' if promotion['routing_decision_found'] else 'NO'}",
        f"- may_promote_current_snapshot: {promotion['may_promote_current_snapshot']}",
        f"- Promotion result: {promotion['promotion_result']}",
        "",
        "## Actionable Verdict",
        f"- Verdict: {verdict}",
        f"- Severity: {severity}",
        "- Owner: governance",
        f"- Required Action: {promotion['reason']}",
        "- Closure Condition: Required governance traces exist and promotion decision is explicit.",
    ]
    if critical_incidents > 0:
        lines.append("- **CRITICAL INCIDENTS OPEN** — promotion blocked until resolved.")
    return "\n".join(lines) + "\n"


def write_run_observability_summary(path: str | Path, **kwargs: Any) -> str:
    """Render and write the observability summary to *path*. Returns the rendered text."""
    summary = render_run_observability_summary(**kwargs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary, encoding="utf-8")
    return summary
