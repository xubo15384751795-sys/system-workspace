from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

# Sparse, high-confidence propagation rules (interpretation layer only).
PROPAGATION_RULES: list[dict[str, Any]] = [
    {
        "source_issue_family": "architecture_drift",
        "target_issue_family": "benchmark_error",
        "edge_type": "structural_to_validation",
        "confidence": "medium",
        "rationale": "Architecture drift often precedes benchmark and validation instability.",
    },
    {
        "source_issue_family": "architecture_drift",
        "target_issue_family": "ml_integrity_violation",
        "edge_type": "structural_to_ml_integrity",
        "confidence": "medium",
        "rationale": "Layer drift can expose training and feedback-loop boundaries.",
    },
    {
        "source_issue_family": "provider_health_issue",
        "target_issue_family": "benchmark_error",
        "edge_type": "upstream_to_validation",
        "confidence": "high",
        "rationale": "Provider degradation commonly surfaces as benchmark regressions.",
    },
    {
        "source_issue_family": "ml_integrity_violation",
        "target_issue_family": "benchmark_error",
        "edge_type": "ml_to_validation",
        "confidence": "high",
        "rationale": "ML pollution and feedback loops undermine benchmark reliability.",
    },
    {
        "source_issue_family": "boundary_violation",
        "target_issue_family": "architecture_drift",
        "edge_type": "boundary_to_drift",
        "confidence": "medium",
        "rationale": "Import boundary violations often co-occur with architecture drift.",
    },
]


def governance_edges(violation_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "edge_id",
        "source_issue_family",
        "target_issue_family",
        "source_subsystem",
        "target_subsystem",
        "edge_type",
        "confidence",
        "rationale",
        "supporting_violation_ids",
    ]
    if violation_df.empty:
        return pd.DataFrame(columns=columns)

    present_families = set(violation_df["issue_family"].astype(str))
    rows: list[dict[str, Any]] = []
    for rule in PROPAGATION_RULES:
        source = rule["source_issue_family"]
        target = rule["target_issue_family"]
        if source not in present_families or target not in present_families:
            continue
        source_rows = violation_df[violation_df["issue_family"] == source]
        target_rows = violation_df[violation_df["issue_family"] == target]
        if source_rows.empty or target_rows.empty:
            continue
        source_subsystem = str(source_rows.iloc[0]["subsystem"])
        target_subsystem = str(target_rows.iloc[0]["subsystem"])
        supporting = sorted(
            set(source_rows["violation_id"].astype(str)) | set(target_rows["violation_id"].astype(str))
        )
        edge_key = [source, target, source_subsystem, target_subsystem, rule["edge_type"]]
        rows.append(
            {
                "edge_id": _edge_id(edge_key),
                "source_issue_family": source,
                "target_issue_family": target,
                "source_subsystem": source_subsystem,
                "target_subsystem": target_subsystem,
                "edge_type": rule["edge_type"],
                "confidence": rule["confidence"],
                "rationale": rule["rationale"],
                "supporting_violation_ids": json.dumps(supporting),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _edge_id(parts: list[Any]) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
#
