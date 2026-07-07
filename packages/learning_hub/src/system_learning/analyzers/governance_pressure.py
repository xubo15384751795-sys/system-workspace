from __future__ import annotations

import pandas as pd

from system_learning.analyzers.recurrence import governance_mode_for, strongest_governance_mode

_MODE_RANK = {
    "observe_only": 0,
    "auto_check_allowed": 1,
    "manual_review_required": 2,
    "proposal_required": 3,
    "blocker": 4,
}


def apply_governance_pressure(
    improvement_df: pd.DataFrame,
    violation_df: pd.DataFrame,
    edges_df: pd.DataFrame,
) -> pd.DataFrame:
    """Explainable rules that escalate governance mode on derived improvement items."""
    if improvement_df.empty:
        return improvement_df

    pressured = improvement_df.copy()
    edge_targets: dict[str, set[str]] = {}
    if not edges_df.empty:
        for _, edge in edges_df.iterrows():
            edge_targets.setdefault(str(edge["target_issue_family"]), set()).add(str(edge["source_issue_family"]))

    for index, row in pressured.iterrows():
        issue_family = str(row["issue_family"])
        severity = str(row["severity"])
        recurrence = int(row["recurrence_count"])
        base_mode = row.get("governance_mode") or governance_mode_for(severity, recurrence)
        modes = [base_mode]

        if recurrence >= 3:
            modes.append("proposal_required")
        if recurrence >= 5 or severity == "critical":
            modes.append("blocker")

        upstream = edge_targets.get(issue_family, set())
        if upstream & {"ml_integrity_violation", "boundary_violation"}:
            modes.append("proposal_required")
        if "ml_integrity_violation" in upstream and recurrence >= 2:
            modes.append("blocker")

        related = violation_df[violation_df["issue_family"] == issue_family]
        if not related.empty:
            modes.append(strongest_governance_mode(related["governance_mode"].astype(str).tolist()))

        pressured.at[index, "governance_mode"] = strongest_governance_mode(modes)
        pressured.at[index, "governance_pressure_score"] = _pressure_score(modes)

    return pressured


def _pressure_score(modes: list[str]) -> int:
    return max(_MODE_RANK.get(mode, 0) for mode in modes)
