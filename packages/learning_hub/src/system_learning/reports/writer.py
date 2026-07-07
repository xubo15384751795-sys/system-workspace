from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from system_learning.runtime.context import RunContext

_INACTIVE_LIFECYCLE = {"closed", "failed"}


def write_reports(
    report_dir: Path,
    ledgers: dict[str, pd.DataFrame],
    run_context: RunContext | None = None,
) -> dict[str, Path]:
    """Write Hub reports from ledger DataFrames and return output paths."""
    report_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    events = ledgers.get("system_event_ledger", pd.DataFrame())
    violations = ledgers.get("violation_ledger", pd.DataFrame())
    improvements = ledgers.get("improvement_queue", pd.DataFrame())
    health = ledgers.get("subsystem_health", pd.DataFrame())

    summary_payload = build_summary_payload(
        events,
        violations,
        improvements,
        health,
        generated_at,
        run_context=run_context.to_dict() if run_context else None,
    )

    paths = {
        "system_health_report": report_dir / "system_health_report.md",
        "improvement_queue": report_dir / "improvement_queue.md",
        "recurrence_report": report_dir / "recurrence_report.md",
        "learning_summary": report_dir / "learning_summary.md",
        "summary": report_dir / "summary.json",
    }

    paths["system_health_report"].write_text(
        render_system_health_report(health, generated_at),
        encoding="utf-8",
    )
    paths["improvement_queue"].write_text(
        render_improvement_queue_report(improvements, generated_at),
        encoding="utf-8",
    )
    paths["recurrence_report"].write_text(
        render_recurrence_report(violations, generated_at),
        encoding="utf-8",
    )
    paths["learning_summary"].write_text(
        render_learning_summary(summary_payload, generated_at),
        encoding="utf-8",
    )
    paths["summary"].write_text(
        json.dumps(summary_payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return paths


def build_summary_payload(
    events: pd.DataFrame,
    violations: pd.DataFrame,
    improvements: pd.DataFrame,
    health: pd.DataFrame,
    generated_at: str,
    *,
    run_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "generated_at": generated_at,
        "overall": {
            "event_count": int(len(events)),
            "violation_count": int(len(violations)),
            "active_improvement_items": active_improvement_count(improvements),
            "improvement_item_count": int(len(improvements)),
            "subsystem_count": int(len(health)),
            "manual_review_events": int(events["requires_manual_review"].sum()) if not events.empty else 0,
        },
        "subsystems": health.to_dict(orient="records") if not health.empty else [],
        "top_issues": top_issues(violations),
        "improvements": improvements.to_dict(orient="records") if not improvements.empty else [],
    }
    if run_context:
        payload["run"] = run_context
    return payload


def active_improvement_count(improvements: pd.DataFrame) -> int:
    if improvements.empty or "lifecycle_state" not in improvements.columns:
        return 0
    states = improvements["lifecycle_state"].astype(str).str.lower()
    return int((~states.isin(_INACTIVE_LIFECYCLE)).sum())


def top_issues(violations: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    if violations.empty:
        return []
    ranked = violations.sort_values(
        ["recurrence_count", "severity"],
        ascending=[False, False],
    ).head(limit)
    return [
        {
            "issue_family": row["issue_family"],
            "subsystem": row["subsystem"],
            "recurrence_count": int(row["recurrence_count"]),
            "severity": row["severity"],
            "governance_mode": row.get("governance_mode", ""),
        }
        for _, row in ranked.iterrows()
    ]


def render_system_health_report(health: pd.DataFrame, generated_at: str) -> str:
    lines = [
        "# System Health Report",
        "",
        f"Generated: {generated_at}",
        "",
    ]
    if health.empty:
        lines.append("No subsystem health data available.")
        return "\n".join(lines) + "\n"

    lines.append("| Subsystem | Band | Score | Events | Violations | Top issue |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- |")
    for _, row in health.iterrows():
        lines.append(
            "| {subsystem} | {health_band} | {health_score} | {event_count} | "
            "{violation_count} | {top_issue_family} |".format(
                subsystem=row["subsystem"],
                health_band=row["health_band"],
                health_score=row["health_score"],
                event_count=row["event_count"],
                violation_count=row["violation_count"],
                top_issue_family=row.get("top_issue_family") or "—",
            )
        )
    return "\n".join(lines) + "\n"


def render_improvement_queue_report(improvements: pd.DataFrame, generated_at: str) -> str:
    lines = [
        "# Improvement Queue",
        "",
        f"Generated: {generated_at}",
        "",
        f"Active items: {active_improvement_count(improvements)} / {len(improvements)}",
        "",
    ]
    if improvements.empty:
        lines.append("No improvement items queued.")
        return "\n".join(lines) + "\n"

    for index, row in improvements.iterrows():
        lines.extend(
            [
                f"## {index + 1}. {row['subsystem']} — {row['issue_family']}",
                "",
                f"- **Lifecycle:** {row['lifecycle_state']}",
                f"- **Priority:** {row['priority']}",
                f"- **Severity:** {row['severity']}",
                f"- **Governance mode:** {row['governance_mode']}",
                f"- **Proposed action:** {row['proposed_action']}",
                f"- **Verification:** {row['verification_criteria']}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def render_recurrence_report(violations: pd.DataFrame, generated_at: str) -> str:
    lines = [
        "# Recurrence Report",
        "",
        f"Generated: {generated_at}",
        "",
    ]
    if violations.empty:
        lines.append("No recurring violations recorded.")
        return "\n".join(lines) + "\n"

    lines.append("| Issue family | Subsystem | Event type | Recurrence | Severity | Governance |")
    lines.append("| --- | --- | --- | ---: | --- | --- |")
    for _, row in violations.iterrows():
        lines.append(
            "| {issue_family} | {subsystem} | {event_type} | {recurrence_count} | "
            "{severity} | {governance_mode} |".format(
                issue_family=row["issue_family"],
                subsystem=row["subsystem"],
                event_type=row["event_type"],
                recurrence_count=row["recurrence_count"],
                severity=row["severity"],
                governance_mode=row.get("governance_mode", ""),
            )
        )
    return "\n".join(lines) + "\n"


def render_learning_summary(summary: dict[str, Any], generated_at: str) -> str:
    overall = summary["overall"]
    lines = [
        "# Learning Summary",
        "",
        f"Generated: {generated_at}",
        "",
        "## Overview",
        "",
        f"- Events ingested: {overall['event_count']}",
        f"- Violation groups: {overall['violation_count']}",
        f"- Active improvement items: {overall['active_improvement_items']}",
        f"- Events requiring manual review: {overall['manual_review_events']}",
        "",
    ]
    top_issues = summary.get("top_issues") or []
    if top_issues:
        lines.append("## Top recurring issues")
        lines.append("")
        for item in top_issues:
            lines.append(
                f"- **{item['issue_family']}** ({item['subsystem']}): "
                f"{item['recurrence_count']}×, severity {item['severity']}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"
