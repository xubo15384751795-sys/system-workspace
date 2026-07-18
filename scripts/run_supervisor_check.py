"""Run supervisor check — boundary audit after each work cycle.

Reads current artifacts and governance policies, produces a structured
supervisor report.  This is the system's boundary audit layer.

The supervisor can FLAG issues but CANNOT:
- Auto-fix problems
- Auto-promote artifacts
- Auto-delete anything
- Grant authority to any artifact

Authority belongs to the main chain. The supervisor only reports.

Usage:
    python3 scripts/run_supervisor_check.py
    python3 scripts/run_supervisor_check.py --json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any



from scripts._runtime_io import ROOT, ensure_dir, load_json, load_yaml  # noqa: E402

CURRENT = ROOT / "Output" / "current"
JUDGMENT = ROOT / "Output" / "judgment"
LEARNING = ROOT / "Output" / "system_learning" / "latest"
DEFERRED_PATH = ROOT / "governance" / "deferred_work_register.yaml"
DATA_AUTHORITY_PATH = ROOT / "governance" / "authority_registry.yaml"
SUPERVISOR_POLICY_PATH = ROOT / "governance" / "opencode_supervisor_policy.yaml"
INCENTIVE_POLICY_PATH = ROOT / "governance" / "incentive_policy.yaml"
SUBMISSIONS_PATH = ROOT / "governance" / "experimental_submission_registry.yaml"
ROUTING_POLICY_PATH = ROOT / "governance" / "output_routing_policy.yaml"
MONITORING_COVERAGE_PATH = LEARNING / "monitoring_coverage.json"
BACKWARD_PASS_PATH = LEARNING / "backward_pass.json"


def _outcome_credit_review_items(backward: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate eligible shadow credit into human-review items only."""
    if not (
        backward.get("status") == "ELIGIBLE_FOR_REVIEW_PRIORITY"
        and backward.get("eligible_to_affect_review_priority") is True
        and backward.get("credit_can_grant_authority") is False
    ):
        return []
    items = []
    for item in (backward.get("review_queue") or [])[:10]:
        action = str(item.get("review_action", "review"))
        items.append({
            "source": "outcome_credit",
            "id": str(item.get("node_id", "unknown")),
            "severity": "medium" if action == "investigate_drag" else "low",
            "action": (
                f"rank={item.get('rank')}; {action}; "
                f"n={item.get('samples')}; "
                f"mean_loss_reduction={item.get('mean_loss_reduction')}"
            ),
        })
    return items


def _check_work_cycle_completeness() -> dict[str, Any]:
    """Check if all declared artifacts exist."""
    required = [
        ("framework_output", CURRENT / "framework_output.json"),
        ("status", CURRENT / "status.json"),
        ("quality_validation", CURRENT / "quality_validation.json"),
        ("judgment", JUDGMENT / "latest.json"),
        ("work_brief", CURRENT / "work_brief.json"),
    ]
    missing = []
    for name, path in required:
        if not path.exists():
            missing.append(name)

    return {
        "status": "PASS" if not missing else "INCOMPLETE",
        "missing": missing,
        "total_required": len(required),
        "present": len(required) - len(missing),
    }


def _check_artifact_consistency() -> dict[str, Any]:
    """Check if artifact dates are consistent."""
    dates = {}
    for name, path, field in [
        ("framework_output", CURRENT / "framework_output.json", "as_of"),
        ("status", CURRENT / "status.json", "date"),
        ("judgment", JUDGMENT / "latest.json", "as_of"),
    ]:
        data = load_json(path)
        if data and data.get(field):
            dates[name] = str(data[field])[:10]

    if not dates:
        return {"status": "NO_DATA", "dates": {}}

    unique_dates = set(dates.values())
    return {
        "status": "PASS" if len(unique_dates) <= 1 else "INCONSISTENT",
        "dates": dates,
        "unique_dates": list(unique_dates),
    }


def _check_unmarked_data() -> dict[str, Any]:
    """Check for non-Harvester data not marked research_only."""
    reg = load_yaml(DATA_AUTHORITY_PATH)
    if not reg:
        return {"status": "NO_REGISTRY", "entries": 0}

    entries = reg.get("data_sources", [])
    unmarked = []
    for entry in entries:
        auth = entry.get("authority", "")
        if auth not in ("research_only_non_harvester", "non_harvester_transitional",
                        "legacy_runtime_store", "legacy_runtime_cache",
                        "migration_artifact", "export_only"):
            unmarked.append(entry.get("path", "unknown"))

    return {
        "status": "PASS" if not unmarked else "WARN",
        "total_entries": len(entries),
        "unmarked": unmarked,
    }


def _check_deferred_work_overdue() -> dict[str, Any]:
    """Check for deferred work past hard_deadline."""
    reg = load_yaml(DEFERRED_PATH)
    if not reg:
        return {"status": "NO_REGISTRY"}

    today = datetime.now(UTC)
    overdue = []
    approaching = []
    for item in reg.get("items", []):
        hard_dl = item.get("hard_deadline")
        if not hard_dl:
            continue
        try:
            deadline = datetime.strptime(str(hard_dl), "%Y-%m-%d").replace(tzinfo=UTC)
            days_left = (deadline - today).days
            if days_left < 0:
                overdue.append({
                    "id": item.get("id", "unknown"),
                    "days_overdue": -days_left,
                    "hard_deadline": str(hard_dl),
                })
            elif days_left <= 14:
                approaching.append({
                    "id": item.get("id", "unknown"),
                    "days_left": days_left,
                    "hard_deadline": str(hard_dl),
                })
        except ValueError:
            pass

    return {
        "status": "PASS" if not overdue else "OVERDUE",
        "overdue": overdue,
        "approaching_deadline": approaching,
    }


def _check_module_activity() -> dict[str, Any]:
    """Check which modules produced output recently."""
    now = datetime.now(UTC)
    active = []
    if CURRENT.exists():
        for item in CURRENT.iterdir():
            if item.is_file() and item.suffix in (".json", ".md"):
                mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=UTC)
                age_hours = (now - mtime).total_seconds() / 3600
                if age_hours < 24:
                    active.append({
                        "artifact": item.name,
                        "age_hours": round(age_hours, 1),
                    })

    return {
        "status": "ACTIVE" if active else "IDLE",
        "active_artifacts": len(active),
        "artifacts": active[:10],
    }


def _check_monitoring_coverage() -> dict[str, Any]:
    """Surface the meta-audit that finds stale and unmonitored artifacts."""
    report = load_json(MONITORING_COVERAGE_PATH)
    if not report:
        return {"status": "FINDINGS", "report_path": str(MONITORING_COVERAGE_PATH), "issue": "monitoring coverage report is missing"}
    source_status = str(report.get("status", "UNKNOWN"))
    status = "PASS" if source_status == "PASS" else "WARN" if source_status == "WARN" else "FINDINGS"
    return {
        "status": status,
        "report_status": source_status,
        "summary": report.get("summary", {}),
        "learning_hub_source_lag": report.get("learning_hub_source_lag", {}),
        "blind_spot_families": report.get("monitoring_blind_spots", []),
        "report_path": str(MONITORING_COVERAGE_PATH),
    }


def _check_current_authority_contamination() -> dict[str, Any]:
    """Check if Output/current/ contains unauthorized artifacts.

    Only artifacts listed in output_routing_policy.yaml groups.current.allowed_artifacts
    should exist in Output/current/. Research/sandbox output must not enter authority readout.
    """
    routing = load_yaml(ROUTING_POLICY_PATH)
    if not routing or not CURRENT.exists():
        return {"status": "NO_ROUTING_POLICY"}

    allowed = set(routing.get("groups", {}).get("current", {}).get("allowed_artifacts", []))
    if not allowed:
        return {"status": "NO_ALLOWED_LIST"}

    actual = {f.name for f in CURRENT.iterdir() if f.is_file()}
    unauthorized = actual - allowed

    return {
        "status": "PASS" if not unauthorized else "CONTAMINATION",
        "allowed_count": len(allowed),
        "actual_count": len(actual),
        "unauthorized": sorted(unauthorized),
    }


def _check_incentive_overreach() -> dict[str, Any]:
    """Check if incentive policy declares automatic authorization.

    Governance can veto but cannot grant core authority.
    Credit must never grant authority.
    """
    policy = load_yaml(INCENTIVE_POLICY_PATH)
    if not policy:
        return {"status": "NO_POLICY"}

    issues = []
    ab = policy.get("authority_boundary", {})

    if not ab:
        issues.append("Missing authority_boundary section")
    else:
        if ab.get("credit_never_grants_authority") is not True:
            issues.append("credit_never_grants_authority must be true")
        if ab.get("governance_can_grant_core_authority") is not False:
            issues.append("governance_can_grant_core_authority must be false")
        if ab.get("canonical_authority_requires_runtime_wiring") is not True:
            issues.append("canonical_authority_requires_runtime_wiring must be true")

    # Check credit sources for direct canonical suggestion
    for name, src in policy.get("credit_sources", {}).items():
        suggests = src.get("suggests_review_for", src.get("promotes_to", ""))
        if suggests in ("canonical", "canonical_candidate"):
            issues.append(f"Credit source '{name}' suggests canonical — credit cannot grant authority")

    # Check review outcomes for automatic promotion
    for outcome in policy.get("review_outcomes", []):
        if "promote_to_canonical" in outcome:
            issues.append(f"Review outcome '{outcome}' implies automatic canonical promotion")

    outcome_credit = policy.get("outcome_credit", {}) or {}
    if outcome_credit.get("enabled"):
        if outcome_credit.get("affects_review_priority_only") is not True:
            issues.append("outcome_credit must affect review priority only")
        if outcome_credit.get("can_affect_authority") is not False:
            issues.append("outcome_credit cannot affect authority")

    return {
        "status": "PASS" if not issues else "OVERREACH",
        "issues": issues,
    }


def _check_priority_drift() -> dict[str, Any]:
    """Check if artifact usage exceeds declared priority.

    An artifact at 'preferred' level should not be used in authority paths
    that require 'canonical' level.
    """
    policy = load_yaml(INCENTIVE_POLICY_PATH)
    if not policy:
        return {"status": "NO_POLICY"}

    # Check if any preferred-level artifact is in Output/current/
    # This is a soft check — the routing policy is the hard gate
    preferred_can_enter_current = policy.get("priority_levels", {}).get("preferred", {}).get(
        "can_enter_authority_current",
        policy.get("priority_levels", {}).get("preferred", {}).get("can_enter_current", True)
    )

    drift_issues = []
    if preferred_can_enter_current:
        drift_issues.append("preferred level allows can_enter_authority_current — should be false")

    return {
        "status": "PASS" if not drift_issues else "DRIFT",
        "issues": drift_issues,
    }


def _check_unreviewed_exceptions() -> dict[str, Any]:
    """Check for expired or incomplete exceptions in submission registry.

    Exceptions need: retire_after, owner, rollback_plan, reviewer, decision_reason.
    Only enforced for non-reject decisions.
    """
    reg = load_yaml(SUBMISSIONS_PATH)
    if not reg:
        return {"status": "NO_REGISTRY"}

    submissions = reg.get("submissions", [])
    if not submissions:
        return {"status": "NO_SUBMISSIONS"}

    issues = []
    today = datetime.now(UTC)
    for sub in submissions:
        sid = sub.get("submission_id", "unknown")
        decision = sub.get("decision")

        # Only enforce completeness for non-reject, non-empty decisions
        if not decision or decision == "reject":
            continue

        # Check retire_after (replaces old "ttl")
        retire_after = sub.get("retire_after")
        if retire_after:
            try:
                retire_date = datetime.strptime(str(retire_after), "%Y-%m-%d").replace(tzinfo=UTC)
                if retire_date < today:
                    issues.append(f"Exception '{sid}' retire_after expired on {retire_after}")
            except ValueError:
                issues.append(f"Exception '{sid}' has invalid retire_after format")
        else:
            issues.append(f"Exception '{sid}' has no retire_after — exceptions must expire")

        # Check rollback_plan (replaces old "rollback")
        if not sub.get("rollback_plan"):
            issues.append(f"Exception '{sid}' has no rollback_plan")

        # Check owner
        if not sub.get("owner"):
            issues.append(f"Exception '{sid}' has no owner")

        # Check reviewer
        if not sub.get("reviewer"):
            issues.append(f"Exception '{sid}' has no reviewer")

        # Check decision_reason
        if not sub.get("decision_reason"):
            issues.append(f"Exception '{sid}' has no decision_reason")

    return {
        "status": "PASS" if not issues else "INCOMPLETE_EXCEPTIONS",
        "total_submissions": len(submissions),
        "issues": issues,
    }


def run_supervisor_check() -> dict[str, Any]:
    """Run all supervisor checks."""
    now = datetime.now(UTC)

    checks = {
        "work_cycle_completeness": _check_work_cycle_completeness(),
        "artifact_consistency": _check_artifact_consistency(),
        "unmarked_data": _check_unmarked_data(),
        "deferred_work_overdue": _check_deferred_work_overdue(),
        "module_activity": _check_module_activity(),
        "monitoring_coverage": _check_monitoring_coverage(),
        "current_authority_contamination": _check_current_authority_contamination(),
        "incentive_overreach": _check_incentive_overreach(),
        "priority_drift": _check_priority_drift(),
        "unreviewed_exceptions": _check_unreviewed_exceptions(),
    }

    # Determine overall status
    statuses = [c.get("status", "UNKNOWN") for c in checks.values()]
    if "OVERDUE" in statuses:
        overall = "OVERDUE"
    elif "CONTAMINATION" in statuses or "OVERREACH" in statuses:
        overall = "BOUNDARY_VIOLATION"
    elif "INCONSISTENT" in statuses or "INCOMPLETE" in statuses or "FINDINGS" in statuses:
        overall = "FINDINGS"
    elif "WARN" in statuses or "DRIFT" in statuses or "INCOMPLETE_EXCEPTIONS" in statuses:
        overall = "WARN"
    else:
        overall = "PASS"

    # Build review queue — supervisor flags for human review, never auto-fixes
    review_queue = []

    # Deferred work overdue
    for item in checks["deferred_work_overdue"].get("overdue", []):
        review_queue.append({
            "source": "deferred_work_overdue",
            "id": item["id"],
            "severity": "high",
            "action": f"Overdue by {item['days_overdue']} days",
        })
    for item in checks["deferred_work_overdue"].get("approaching_deadline", []):
        review_queue.append({
            "source": "deadline_approaching",
            "id": item["id"],
            "severity": "medium",
            "action": f"{item['days_left']} days to deadline",
        })

    # Current authority contamination
    for artifact in checks["current_authority_contamination"].get("unauthorized", []):
        review_queue.append({
            "source": "current_authority_contamination",
            "id": artifact,
            "severity": "high",
            "action": f"Unauthorized artifact in Output/current/: {artifact}",
        })

    # Incentive overreach
    for issue in checks["incentive_overreach"].get("issues", []):
        review_queue.append({
            "source": "incentive_overreach",
            "id": "incentive_policy",
            "severity": "high",
            "action": issue,
        })

    # Priority drift
    for issue in checks["priority_drift"].get("issues", []):
        review_queue.append({
            "source": "priority_drift",
            "id": "priority_config",
            "severity": "medium",
            "action": issue,
        })

    # Unreviewed exceptions
    for issue in checks["unreviewed_exceptions"].get("issues", []):
        review_queue.append({
            "source": "unreviewed_exceptions",
            "id": "submission_registry",
            "severity": "medium",
            "action": issue,
        })

    # Monitoring blind spots and stale weekly artifacts
    monitoring = checks["monitoring_coverage"]
    monitoring_summary = monitoring.get("summary", {})
    stale_count = int(monitoring_summary.get("weekly_stale_or_missing_count", 0))
    no_clock_count = int(monitoring_summary.get("weekly_no_content_clock_count", 0))
    if monitoring.get("status") == "FINDINGS" and not monitoring_summary:
        review_queue.append({
            "source": "monitoring_coverage",
            "id": "missing_monitoring_report",
            "severity": "high",
            "action": monitoring.get("issue", "Monitoring coverage audit failed"),
        })
    if stale_count or no_clock_count:
        review_queue.append({
            "source": "monitoring_coverage",
            "id": "weekly_content_freshness",
            "severity": "high" if stale_count else "medium",
            "action": f"{stale_count} stale/missing weekly artifact(s); {no_clock_count} without a content clock",
        })
    for family in monitoring.get("blind_spot_families", [])[:10]:
        review_queue.append({
            "source": "monitoring_coverage",
            "id": family.get("family", "unknown"),
            "severity": "medium",
            "action": f"{family.get('count', 0)} artifact(s) have no registered monitor coverage",
        })

    # Outcome credit reorders human attention only. It does not affect the
    # supervisor status, gates, permissions, or authority graph.
    backward = load_json(BACKWARD_PASS_PATH) or {}
    review_queue.extend(_outcome_credit_review_items(backward))

    return {
        "timestamp": now.isoformat(),
        "overall_status": overall,
        "checks": checks,
        "review_queue": review_queue,
        "authority_note": (
            "This report is observation only. "
            "Supervisor can flag issues but cannot auto-fix, auto-promote, or grant authority."
        ),
    }


def generate_markdown(results: dict[str, Any]) -> str:
    """Generate markdown supervisor report."""
    lines = [
        "# Supervisor Check — Boundary Audit",
        "",
        f"**Timestamp:** {results['timestamp']}",
        f"**Overall Status:** {results['overall_status']}",
        "",
        "> Supervisor can flag issues but cannot auto-fix, auto-promote, or grant authority.",
        "> Authority belongs to the main chain.",
        "",
        "---",
        "",
    ]

    status_icons = {
        "PASS": "✅", "ACTIVE": "✅", "NO_DATA": "⚪", "NO_REGISTRY": "⚪",
        "NO_ROUTING_POLICY": "⚪", "NO_ALLOWED_LIST": "⚪", "NO_SUBMISSIONS": "⚪",
        "IDLE": "⚪", "INCOMPLETE": "⚠️", "INCONSISTENT": "⚠️",
        "WARN": "⚠️", "OVERDUE": "❌", "FINDINGS": "⚠️",
        "CONTAMINATION": "🚨", "OVERREACH": "🚨", "BOUNDARY_VIOLATION": "🚨",
        "DRIFT": "⚠️", "INCOMPLETE_EXCEPTIONS": "⚠️",
    }

    for check_name, check_data in results["checks"].items():
        icon = status_icons.get(check_data["status"], "❓")
        lines.append(f"## {icon} {check_name}")
        lines.append("")
        lines.append(f"**Status:** {check_data['status']}")
        lines.append("")

        # Show key details
        if check_data.get("missing"):
            lines.append(f"Missing: {', '.join(check_data['missing'])}")
            lines.append("")
        if check_data.get("dates"):
            lines.append("Dates:")
            for k, v in check_data["dates"].items():
                lines.append(f"  - {k}: {v}")
            lines.append("")
        if check_data.get("overdue"):
            lines.append("Overdue:")
            for item in check_data["overdue"]:
                lines.append(f"  - {item['id']}: {item['days_overdue']} days overdue")
            lines.append("")
        if check_data.get("approaching_deadline"):
            lines.append("Approaching deadline:")
            for item in check_data["approaching_deadline"]:
                lines.append(f"  - {item['id']}: {item['days_left']} days left")
            lines.append("")
        if check_data.get("unauthorized"):
            lines.append("Unauthorized in Output/current/:")
            for artifact in check_data["unauthorized"]:
                lines.append(f"  - 🚨 {artifact}")
            lines.append("")
        if check_data.get("issues"):
            lines.append("Issues:")
            for issue in check_data["issues"]:
                lines.append(f"  - ⚠️ {issue}")
            lines.append("")

    if results.get("review_queue"):
        lines += [
            "---",
            "",
            "## Review Queue",
            "",
            "*These items require human review. Supervisor cannot auto-fix.*",
            "",
        ]
        for item in results["review_queue"]:
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(item["severity"], "⚪")
            lines.append(f"- {severity_icon} [{item['severity']}] **{item['source']}** — {item['id']}: {item['action']}")
        lines.append("")

    lines += [
        "---",
        "",
        "*Generated by scripts/run_supervisor_check.py*",
        "*Authority: governance/opencode_supervisor_policy.yaml*",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run supervisor boundary audit")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    results = run_supervisor_check()

    ensure_dir(LEARNING)

    json_path = LEARNING / "supervisor_check.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md_path = LEARNING / "supervisor_check.md"
    md_path.write_text(generate_markdown(results), encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(generate_markdown(results))


if __name__ == "__main__":
    main()
