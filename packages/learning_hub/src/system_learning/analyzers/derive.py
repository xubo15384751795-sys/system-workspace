from __future__ import annotations

import pandas as pd

from system_learning.analyzers.edges import governance_edges
from system_learning.analyzers.governance_pressure import apply_governance_pressure
from system_learning.analyzers.recurrence import (
    event_ledger,
    improvement_queue,
    subsystem_health,
    violation_ledger,
)
from system_learning.governance.lifecycle_events import derive_lifecycle_states


def build_derived_ledgers(
    event_df: pd.DataFrame,
    lifecycle_df: pd.DataFrame,
    *,
    metadata_cache: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Derived materialized views from append-only event + lifecycle ledgers."""
    violation_df = violation_ledger(event_df)
    edges_df = governance_edges(violation_df)
    lifecycle_states = derive_lifecycle_states(lifecycle_df, metadata_cache=metadata_cache)
    improvement_df = improvement_queue(
        event_df,
        violation_df,
        lifecycle_states=lifecycle_states,
        metadata_cache=metadata_cache,
    )
    improvement_df = apply_governance_pressure(improvement_df, violation_df, edges_df)
    health_df = subsystem_health(event_df, violation_df)
    return {
        "system_event_ledger": event_df,
        "violation_ledger": violation_df,
        "event_edges": edges_df,
        "improvement_queue": improvement_df,
        "subsystem_health": health_df,
    }


def build_ledgers(events: list[dict], existing_improvements: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Backward-compatible helper for tests and direct event lists."""
    event_df = event_ledger(events)
    return build_derived_ledgers(event_df, pd.DataFrame(), metadata_cache=existing_improvements)
