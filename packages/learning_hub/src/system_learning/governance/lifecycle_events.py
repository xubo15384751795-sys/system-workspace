from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from system_learning.governance.lifecycle import LIFECYCLE_STATES, normalize_lifecycle_state

LIFECYCLE_COLUMNS = [
    "event_id",
    "improvement_id",
    "transition",
    "timestamp",
    "recorded_at",
    "recorded_by_run",
    "actor",
    "notes",
    "payload",
]


def lifecycle_event(
    *,
    improvement_id: str,
    transition: str,
    recorded_by_run: str,
    timestamp: str | None = None,
    actor: str = "",
    notes: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transition = normalize_lifecycle_state(transition)
    recorded_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    ts = timestamp or recorded_at
    raw = json.dumps(
        {"improvement_id": improvement_id, "transition": transition, "timestamp": ts, "recorded_by_run": recorded_by_run},
        sort_keys=True,
    )
    return {
        "event_id": f"lc-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}",
        "improvement_id": improvement_id,
        "transition": transition,
        "timestamp": ts,
        "recorded_at": recorded_at,
        "recorded_by_run": recorded_by_run,
        "actor": actor,
        "notes": notes,
        "payload": json.dumps(payload or {}, sort_keys=True, default=str),
    }


def lifecycle_events_frame(events: list[dict] | pd.DataFrame | None) -> pd.DataFrame:
    if events is None:
        return pd.DataFrame(columns=LIFECYCLE_COLUMNS)
    if isinstance(events, pd.DataFrame):
        frame = events.copy()
    else:
        frame = pd.DataFrame(events, columns=LIFECYCLE_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=LIFECYCLE_COLUMNS)
    for column in LIFECYCLE_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[LIFECYCLE_COLUMNS]


def derive_lifecycle_states(
    lifecycle_df: pd.DataFrame,
    *,
    metadata_cache: pd.DataFrame | None = None,
) -> dict[str, dict[str, str]]:
    """Derive current lifecycle + human metadata from append-only transitions."""
    states: dict[str, dict[str, str]] = {}
    if not lifecycle_df.empty:
        ordered = lifecycle_df.sort_values(["improvement_id", "timestamp", "recorded_at"])
        for _, row in ordered.iterrows():
            improvement_id = str(row["improvement_id"])
            transition = normalize_lifecycle_state(str(row["transition"]))
            if transition not in LIFECYCLE_STATES:
                continue
            entry = states.setdefault(improvement_id, {})
            entry["lifecycle_state"] = transition
            if row.get("actor"):
                entry["owner"] = str(row["actor"])
            if row.get("notes"):
                entry["approval_notes"] = str(row["notes"])
            payload = row.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            if isinstance(payload, dict):
                for field in ("decision", "deadline"):
                    if payload.get(field):
                        entry[field] = str(payload[field])

    if metadata_cache is not None and not metadata_cache.empty:
        state_column = "lifecycle_state" if "lifecycle_state" in metadata_cache.columns else "approval_state"
        for _, row in metadata_cache.iterrows():
            improvement_id = str(row.get("improvement_id", ""))
            if not improvement_id:
                continue
            entry = states.setdefault(improvement_id, {})
            if state_column in metadata_cache.columns:
                entry.setdefault(
                    "lifecycle_state",
                    normalize_lifecycle_state(str(row.get(state_column, "proposed"))),
                )
            for field in (
                "owner",
                "approval_notes",
                "verification_criteria",
                "closed_at",
                "created_at",
                "decision",
                "deadline",
            ):
                if field in metadata_cache.columns and pd.notna(row.get(field)) and str(row.get(field, "")).strip():
                    entry.setdefault(field, str(row[field]))

    return states


def migrate_improvement_queue_to_lifecycle_events(
    queue: pd.DataFrame,
    *,
    recorded_by_run: str,
) -> list[dict]:
    """One-time style migration: snapshot prior derived queue states into lifecycle events."""
    if queue is None or queue.empty or "improvement_id" not in queue.columns:
        return []
    state_column = "lifecycle_state" if "lifecycle_state" in queue.columns else "approval_state"
    events: list[dict] = []
    for _, row in queue.iterrows():
        improvement_id = str(row["improvement_id"])
        transition = normalize_lifecycle_state(str(row.get(state_column, "proposed")))
        events.append(
            lifecycle_event(
                improvement_id=improvement_id,
                transition=transition,
                recorded_by_run=recorded_by_run,
                timestamp=str(row.get("updated_at") or row.get("created_at") or ""),
                actor=str(row.get("owner") or ""),
                notes=str(row.get("approval_notes") or ""),
                payload={"migrated_from": "improvement_queue"},
            )
        )
    return events


def proposed_events_for_improvements(
    improvement_ids: list[str],
    existing_lifecycle: pd.DataFrame,
    *,
    recorded_by_run: str,
) -> list[dict]:
    known = set(existing_lifecycle["improvement_id"].astype(str)) if not existing_lifecycle.empty else set()
    events: list[dict] = []
    for improvement_id in improvement_ids:
        if improvement_id in known:
            continue
        events.append(
            lifecycle_event(
                improvement_id=improvement_id,
                transition="proposed",
                recorded_by_run=recorded_by_run,
                notes="auto-proposed from recurrence",
            )
        )
    return events
