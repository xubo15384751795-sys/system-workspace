from __future__ import annotations

from typing import Any, cast

import pandas as pd

from system_learning.governance.lifecycle import LIFECYCLE_STATES, normalize_lifecycle_state


def verify_improvement_lifecycle(queue: pd.DataFrame) -> dict[str, Any]:
    """Validate lifecycle states in the improvement queue (pure check, no I/O)."""
    issues: list[dict[str, str]] = []
    if queue is None or queue.empty:
        return {"ok": True, "issues": issues, "item_count": 0}

    state_column = "lifecycle_state" if "lifecycle_state" in queue.columns else "approval_state"
    for index, row in queue.iterrows():
        raw = str(row.get(state_column, "proposed"))
        state = normalize_lifecycle_state(raw)
        if state not in LIFECYCLE_STATES:
            issues.append(
                {
                    "improvement_id": str(row.get("improvement_id", index)),
                    "kind": "invalid_state",
                    "detail": f"Unknown lifecycle state {raw!r}",
                }
            )
        if raw != state and raw.lower() not in LIFECYCLE_STATES:
            issues.append(
                {
                    "improvement_id": str(row.get("improvement_id", index)),
                    "kind": "normalized_state",
                    "detail": f"Coerced {raw!r} -> {state!r}",
                }
            )

    return {
        "ok": not issues,
        "issues": issues,
        "item_count": int(len(queue)),
        "allowed_transitions": {state: sorted(targets) for state, targets in _transition_map().items()},
    }


def _transition_map() -> dict[str, set[str]]:
    from system_learning.governance.lifecycle import ALLOWED_TRANSITIONS

    return cast(dict[str, set[str]], ALLOWED_TRANSITIONS)
