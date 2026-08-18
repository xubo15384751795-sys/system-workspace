"""Fail-closed contract for Learning Hub improvement queue metadata."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

DECISION_VALUES = frozenset({"accepted", "rejected", "deferred"})
_NON_AUTHORITY_VALUES = frozenset({"", "none", "diagnostic", "diagnostic_only", "governance_only"})


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return bool(str(value).strip())


def _has_evidence(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(_has_value(item) for item in value)
    if not _has_value(value):
        return False
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value.strip() not in {"[]", "{}", "null"}
        if isinstance(parsed, list):
            return any(_has_value(item) for item in parsed)
        return _has_value(parsed)
    return True


def improvement_queue_contract_violations(queue: pd.DataFrame | None) -> list[dict[str, str]]:
    """Return metadata violations without mutating or approving queue items."""
    if queue is None or queue.empty:
        return []

    violations: list[dict[str, str]] = []
    for index, row in queue.iterrows():
        improvement_id = str(row.get("improvement_id") or index)
        if not _has_value(row.get("owner")):
            violations.append({"improvement_id": improvement_id, "kind": "missing_owner"})
        if not _has_value(row.get("deadline")):
            violations.append({"improvement_id": improvement_id, "kind": "missing_deadline"})
        if not _has_evidence(row.get("evidence_paths")) and not _has_evidence(
            row.get("evidence_event_ids")
        ):
            violations.append({"improvement_id": improvement_id, "kind": "missing_evidence"})
        decision = str(row.get("decision") or "").strip().lower()
        if not decision:
            violations.append({"improvement_id": improvement_id, "kind": "missing_decision"})
        elif decision not in DECISION_VALUES:
            violations.append(
                {
                    "improvement_id": improvement_id,
                    "kind": "invalid_decision",
                    "value": decision,
                }
            )
        for field in (
            "authority",
            "authority_mode",
            "allowed_to_affect_core_judgment",
            "can_affect_core_judgment",
        ):
            value = str(row.get(field) or "").strip().casefold()
            if value not in _NON_AUTHORITY_VALUES:
                violations.append(
                    {
                        "improvement_id": improvement_id,
                        "kind": "authority_grant_attempt",
                        "field": field,
                    }
                )
    return violations


__all__ = ["DECISION_VALUES", "improvement_queue_contract_violations"]
