from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pandas as pd

ISSUE_RULES = [
    ("governance_work_item", ("governance_open_thread", "governance_work_item")),
    (
        "boundary_violation",
        ("boundary_violation", "import_boundary", "forbidden_dependency", "forbidden_modify", "write_attempt", "manifest", "config"),
    ),
    ("architecture_drift", ("architecture_drift", "oversized_file", "module_growth")),
    ("benchmark_error", ("benchmark", "validation_error", "metric_error", "calibration")),
    ("provider_health_issue", ("provider", "health", "outage", "rate_limit", "timeout", "latency")),
    ("claim_overreach", ("claim", "overreach", "unsupported_claim", "paper", "wiki")),
    ("ui_governance_issue", ("ui", "interface", "render", "workflow")),
    (
        "ml_integrity_violation",
        ("ml_constitution", "ml_pollution", "ml_integrity", "feedback_loop", "sycophancy"),
    ),
]

SEVERITY_WEIGHT = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
HEALTH_EVENT_PENALTY = {"info": 0, "low": 1, "medium": 3, "high": 10, "critical": 35}


def event_ledger(events: list[dict]) -> pd.DataFrame:
    columns = [
        "event_id",
        "timestamp",
        "subsystem",
        "event_type",
        "severity",
        "source_tool",
        "context_type",
        "confidence",
        "boundary_type",
        "target_subsystem",
        "related_paths",
        "governance_mode",
        "run_id",
        "bundle_id",
        "payload",
        "recommended_action",
        "source_report_path",
        "requires_manual_review",
    ]
    df = pd.DataFrame(events, columns=columns)
    if df.empty:
        return pd.DataFrame(columns=columns)
    defaults = {
        "source_tool": "",
        "context_type": "unknown",
        "confidence": "medium",
        "boundary_type": "",
        "target_subsystem": "",
        "related_paths": [],
        "governance_mode": "observe_only",
    }
    for column, default in defaults.items():
        df[column] = df[column].map(lambda value, fallback=default: fallback if is_missing(value) else value)
    df["payload"] = df["payload"].map(lambda value: json.dumps(value, sort_keys=True, default=str))
    df["related_paths"] = df["related_paths"].map(lambda value: json.dumps(value, sort_keys=True, default=str))
    df["requires_manual_review"] = df["requires_manual_review"].astype(bool)
    return df.drop_duplicates(subset=["event_id"]).sort_values(["timestamp", "event_id"]).reset_index(drop=True)


def violation_ledger(event_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "violation_id",
        "issue_family",
        "subsystem",
        "target_subsystem",
        "boundary_type",
        "governance_mode",
        "event_type",
        "severity",
        "first_seen",
        "last_seen",
        "recurrence_count",
        "event_ids",
        "source_report_paths",
        "requires_manual_review",
        "recommended_action",
    ]
    if event_df.empty:
        return pd.DataFrame(columns=columns)

    enriched = event_df.copy()
    enriched["issue_family"] = enriched.apply(classify_issue_family, axis=1)
    enriched = enriched[enriched["issue_family"] != ""]
    if enriched.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for key, group in enriched.groupby(["issue_family", "subsystem", "event_type"], dropna=False):
        issue_family, subsystem, event_type = key
        event_ids = sorted(group["event_id"].astype(str).tolist())
        paths = sorted({p for p in group["source_report_path"].astype(str).tolist() if p})
        severity = max(group["severity"].astype(str), key=lambda s: SEVERITY_WEIGHT.get(s, 0))
        rows.append(
            {
                "violation_id": stable_id([issue_family, subsystem, event_type, *event_ids]),
                "issue_family": issue_family,
                "subsystem": subsystem,
                "target_subsystem": most_common_nonempty(group["target_subsystem"].astype(str).tolist()) or subsystem,
                "boundary_type": most_common_nonempty(group["boundary_type"].astype(str).tolist()),
                "governance_mode": strongest_governance_mode(group["governance_mode"].astype(str).tolist()),
                "event_type": event_type,
                "severity": severity,
                "first_seen": group["timestamp"].min(),
                "last_seen": group["timestamp"].max(),
                "recurrence_count": int(len(group)),
                "event_ids": json.dumps(event_ids),
                "source_report_paths": json.dumps(paths),
                "requires_manual_review": bool(group["requires_manual_review"].any()),
                "recommended_action": most_common_nonempty(group["recommended_action"].astype(str).tolist()),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(["issue_family", "subsystem"]).reset_index(drop=True)


def improvement_queue(
    event_df: pd.DataFrame,
    violation_df: pd.DataFrame,
    *,
    lifecycle_states: dict[str, dict[str, str]] | None = None,
    metadata_cache: pd.DataFrame | None = None,
    existing_improvements: pd.DataFrame | None = None,
) -> pd.DataFrame:
    columns = [
        "improvement_id",
        "subsystem",
        "target_subsystem",
        "issue_family",
        "boundary_type",
        "systemic_risk_tag",
        "proposed_action",
        "lifecycle_state",
        "approval_status",
        "decision",
        "approval_notes",
        "owner",
        "deadline",
        "requires_manual_approval",
        "governance_mode",
        "governance_pressure_score",
        "severity",
        "impact_level",
        "priority",
        "recurrence_count",
        "risk_if_ignored",
        "verification_criteria",
        "evidence_paths",
        "related_events",
        "evidence_event_ids",
        "first_seen",
        "last_seen",
        "created_at",
        "updated_at",
        "closed_at",
    ]
    cache = metadata_cache if metadata_cache is not None else existing_improvements
    preserved_metadata = preserved_improvement_metadata(cache)
    now = current_timestamp()
    rows = []
    for _, row in violation_df.iterrows():
        action = recommended_action_for(row)
        improvement_id = stable_id([row["subsystem"], row["issue_family"], row["event_type"], action])
        state_values = (lifecycle_states or {}).get(improvement_id, {})
        preserved_values = preserved_metadata.get(improvement_id, {})
        lifecycle_state = state_values.get("lifecycle_state", preserved_values.get("lifecycle_state", "proposed"))
        rows.append(
            {
                "improvement_id": improvement_id,
                "subsystem": row["subsystem"],
                "target_subsystem": preserved_values.get("target_subsystem", row.get("target_subsystem", row["subsystem"])),
                "issue_family": row["issue_family"],
                "boundary_type": row.get("boundary_type") or boundary_type_for(row["issue_family"]),
                "systemic_risk_tag": systemic_risk_tag_for(row["issue_family"]),
                "proposed_action": action,
                "lifecycle_state": lifecycle_state,
                "approval_status": preserved_values.get("approval_status", approval_status_for(lifecycle_state)),
                "decision": preserved_values.get("decision", ""),
                "approval_notes": state_values.get("approval_notes", preserved_values.get("approval_notes", "")),
                "owner": state_values.get("owner", preserved_values.get("owner", "")),
                "deadline": state_values.get("deadline", preserved_values.get("deadline", "")),
                "requires_manual_approval": True,
                "governance_mode": row.get("governance_mode") or governance_mode_for(row["severity"], int(row["recurrence_count"])),
                "governance_pressure_score": 0,
                "severity": row["severity"],
                "impact_level": impact_level_for(row["severity"]),
                "priority": priority(row["severity"], int(row["recurrence_count"])),
                "recurrence_count": int(row["recurrence_count"]),
                "risk_if_ignored": risk_if_ignored_for(row["issue_family"]),
                "verification_criteria": state_values.get(
                    "verification_criteria",
                    preserved_values.get("verification_criteria", verification_criteria_for(row["issue_family"])),
                ),
                "evidence_paths": row["source_report_paths"],
                "related_events": row["event_ids"],
                "evidence_event_ids": row["event_ids"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "created_at": preserved_values.get("created_at", row["first_seen"] or now),
                "updated_at": now,
                "closed_at": state_values.get("closed_at", preserved_values.get("closed_at", "")),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(["priority", "subsystem"], ascending=[False, True]).reset_index(drop=True)


def subsystem_health(event_df: pd.DataFrame, violation_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "subsystem",
        "event_count",
        "violation_count",
        "manual_review_count",
        "critical_count",
        "high_count",
        "health_score",
        "health_band",
        "top_issue_family",
    ]
    if event_df.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for subsystem, group in event_df.groupby("subsystem"):
        related = violation_df[violation_df["subsystem"] == subsystem]
        violation_count = int(related["recurrence_count"].sum()) if not related.empty else 0
        manual_review_count = int(group["requires_manual_review"].sum())
        critical_count = int((group["severity"] == "critical").sum())
        high_count = int((group["severity"] == "high").sum())
        severity_penalty = sum(HEALTH_EVENT_PENALTY.get(str(severity), 0) for severity in group["severity"])
        penalty = severity_penalty + manual_review_count * 2 + high_count * 8 + critical_count * 15
        score = max(0, min(100, 100 - penalty))
        band = "healthy" if score >= 85 else "watch" if score >= 65 else "degraded" if score >= 40 else "critical"
        top_issue_family = ""
        if not related.empty:
            top_issue_family = str(related.groupby("issue_family")["recurrence_count"].sum().idxmax())
        rows.append(
            {
                "subsystem": subsystem,
                "event_count": int(len(group)),
                "violation_count": violation_count,
                "manual_review_count": manual_review_count,
                "critical_count": critical_count,
                "high_count": high_count,
                "health_score": score,
                "health_band": band,
                "top_issue_family": top_issue_family,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("health_score").reset_index(drop=True)


def classify_issue_family(row: pd.Series) -> str:
    haystack = " ".join(
        [
            str(row.get("event_type", "")).lower(),
            str(row.get("boundary_type", "")).lower(),
            payload_value_text(row.get("payload", "")).lower(),
            str(row.get("recommended_action", "")).lower(),
            str(row.get("source_report_path", "")).lower(),
        ]
    )
    for family, tokens in ISSUE_RULES:
        if any(token in haystack for token in tokens):
            return family
    return ""


def recommended_action_for(row: pd.Series) -> str:
    family = row["issue_family"]
    if family == "governance_work_item":
        return str(row.get("recommended_action") or "Review the migrated governance work item.")
    if family == "boundary_violation":
        return "Clarify governance boundaries and require producer-side approval evidence before implementation."
    if family == "architecture_drift":
        return "Review architecture drift and either approve the boundary exception or move the code to the owning layer."
    if family == "benchmark_error":
        return "Review recurring benchmark errors and require source systems to emit benchmark diagnostics."
    if family == "provider_health_issue":
        return "Review provider reliability recurrence and define producer-side health thresholds."
    if family == "claim_overreach":
        return "Require manual guardian approval before claim or paper changes proceed."
    if family == "ui_governance_issue":
        return "Review UI recurrence and propose workflow or validation improvements for manual approval."
    if family == "ml_integrity_violation":
        return (
            "Halt ML signal promotion if RED violations are present; review pollution evidence "
            "and require human governance sign-off before re-enabling ML-influenced paths."
        )
    return "Review recurring governance issue and decide whether a producer-side improvement is needed."


def preserved_improvement_metadata(existing: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if existing is None or existing.empty or "improvement_id" not in existing.columns:
        return {}
    preserve_columns = {
        "approval_status",
        "decision",
        "approval_notes",
        "owner",
        "deadline",
        "verification_criteria",
        "created_at",
        "closed_at",
    }
    rows = {}
    for _, row in existing.iterrows():
        rows[str(row["improvement_id"])] = {
            column: row[column]
            for column in preserve_columns
            if column in existing.columns and not is_missing(row[column])
        }
    return rows


def priority(severity: str, recurrence_count: int) -> int:
    return SEVERITY_WEIGHT.get(str(severity), 0) * 10 + min(recurrence_count, 10)


def approval_status_for(lifecycle_state: str) -> str:
    if lifecycle_state in {"approved", "implemented", "verified"}:
        return "approved"
    if lifecycle_state == "failed":
        return "rejected"
    return "pending"


def governance_mode_for(severity: str, recurrence_count: int) -> str:
    if severity == "critical":
        return "blocker"
    if severity == "high" or recurrence_count >= 3:
        return "proposal_required"
    return "manual_review_required"


def impact_level_for(severity: str) -> str:
    if severity in {"critical", "high"}:
        return "high"
    if severity == "medium":
        return "medium"
    return "low"


def boundary_type_for(issue_family: str) -> str:
    return {
        "boundary_violation": "import_boundary",
        "architecture_drift": "architecture_drift",
        "benchmark_error": "runtime_failure",
        "provider_health_issue": "runtime_failure",
        "claim_overreach": "report_quality",
        "ui_governance_issue": "architecture_drift",
        "ml_integrity_violation": "feedback_loop",
    }.get(issue_family, "architecture_drift")


def systemic_risk_tag_for(issue_family: str) -> str:
    return {
        "boundary_violation": "layer_collapse",
        "architecture_drift": "schema_instability",
        "benchmark_error": "evidence_gap",
        "provider_health_issue": "feedback_loop_missing",
        "claim_overreach": "manual_override_risk",
        "ui_governance_issue": "state_leakage",
        "ml_integrity_violation": "feedback_loop_missing",
    }.get(issue_family, "schema_instability")


def risk_if_ignored_for(issue_family: str) -> str:
    return {
        "boundary_violation": "Peer system boundaries may collapse into direct implementation coupling.",
        "architecture_drift": "Layer drift may normalize unclear ownership and make future changes harder to route.",
        "benchmark_error": "Recurring validation failures may erode model reliability evidence.",
        "provider_health_issue": "Provider instability may silently degrade upstream evidence quality.",
        "claim_overreach": "Unsupported claims may leak into reports or paper text.",
        "ui_governance_issue": "Workflow drift may hide reliability problems from reviewers.",
        "ml_integrity_violation": (
            "ML may circularly confirm Deformation or Harvester conclusions, "
            "closing feedback loops and contaminating the evidence base."
        ),
    }.get(issue_family, "Recurring governance drift may become normalized and harder to reverse.")


def verification_criteria_for(issue_family: str) -> str:
    return {
        "boundary_violation": "A repeat cartography run shows no matching boundary violation, and peer-system approval evidence is attached if behavior changed.",
        "architecture_drift": "A repeat cartography run shows the drift is removed or a routing decision records the approved exception.",
        "benchmark_error": "The source system emits benchmark diagnostics and a later run shows the recurrence has stopped.",
        "provider_health_issue": "The source system emits provider health thresholds and a later run remains within threshold.",
        "claim_overreach": "Guardian review confirms affected claims have evidence and no unsupported text remains.",
        "ui_governance_issue": "UI workflow validation or review confirms the recurrence no longer appears.",
        "ml_integrity_violation": (
            "A pollution check passes with no RED violations, ML signals remain under "
            "Output/state/ml_signals/, and human governance sign-off is recorded."
        ),
    }.get(issue_family, "A later Hub run shows the recurrence has stopped and evidence paths are linked.")


def current_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def payload_value_text(value: Any) -> str:
    if isinstance(value, str):
        text = value
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return text
        value = decoded
    if isinstance(value, dict):
        return " ".join(payload_value_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(payload_value_text(item) for item in value)
    return "" if is_missing(value) else str(value)


def most_common_nonempty(values: list[str]) -> str:
    cleaned = [
        text
        for value in values
        if (text := str(value).strip()) and text.lower() not in {"nan", "none", "<na>"}
    ]
    if not cleaned:
        return ""
    return Counter(cleaned).most_common(1)[0][0]


def strongest_governance_mode(values: list[str]) -> str:
    weights = {
        "observe_only": 0,
        "auto_check_allowed": 1,
        "manual_review_required": 2,
        "proposal_required": 3,
        "blocker": 4,
    }
    return max((value for value in values if value in weights), key=lambda value: weights[value], default="observe_only")


def stable_id(parts: list[Any]) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def is_missing(value: Any) -> bool:
    if isinstance(value, (list, tuple, dict, set)):
        return False
    return bool(pd.isna(value))
