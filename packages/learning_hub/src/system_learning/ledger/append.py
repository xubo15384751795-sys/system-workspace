from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from system_learning.analyzers.recurrence import event_ledger
from system_learning.governance.lifecycle_events import LIFECYCLE_COLUMNS, lifecycle_events_frame

EVENT_LOG_FILE = "system_event_log.parquet"
EVENT_SNAPSHOT_FILE = "system_event_ledger.parquet"
LIFECYCLE_LEDGER_FILE = "improvement_lifecycle_ledger.parquet"

RECORD_COLUMNS = ["recorded_at", "recorded_by_run"]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def read_append_ledger(path: Path, base_columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=[*base_columns, *RECORD_COLUMNS])
    frame = pd.read_parquet(path)
    for column in [*base_columns, *RECORD_COLUMNS]:
        if column not in frame.columns:
            frame[column] = ""
    return frame


def bootstrap_event_log(ledger_dir: Path) -> None:
    """Migrate legacy snapshot-only ledger into append-only log."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    log_path = ledger_dir / EVENT_LOG_FILE
    if log_path.exists():
        return
    legacy = ledger_dir / EVENT_SNAPSHOT_FILE
    if not legacy.exists():
        return
    frame = pd.read_parquet(legacy)
    if frame.empty:
        return
    if "recorded_at" not in frame.columns:
        frame = frame.copy()
        frame["recorded_at"] = _now()
        frame["recorded_by_run"] = "bootstrap"
    frame.to_parquet(log_path, index=False)


def append_system_events(ledger_dir: Path, events: list[dict], recorded_by_run: str) -> pd.DataFrame:
    """Append-only ingest: new observations are recorded, existing event_ids are not duplicated."""
    ledger_dir.mkdir(parents=True, exist_ok=True)
    bootstrap_event_log(ledger_dir)
    path = ledger_dir / EVENT_LOG_FILE
    incoming = event_ledger(events)
    if not incoming.empty:
        incoming = incoming.copy()
        incoming["recorded_at"] = _now()
        incoming["recorded_by_run"] = recorded_by_run

    existing = read_append_ledger(path, list(incoming.columns) if not incoming.empty else _event_columns())
    if existing.empty:
        merged = incoming
    elif incoming.empty:
        merged = existing
    else:
        known_ids = set(existing["event_id"].astype(str))
        novel = incoming[~incoming["event_id"].astype(str).isin(known_ids)]
        merged = pd.concat([existing, novel], ignore_index=True)

    merged = merged.sort_values(["timestamp", "event_id", "recorded_at"]).reset_index(drop=True)
    merged.to_parquet(path, index=False)
    return merged


def append_lifecycle_events(ledger_dir: Path, events: list[dict], recorded_by_run: str) -> pd.DataFrame:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_dir / LIFECYCLE_LEDGER_FILE
    incoming = lifecycle_events_frame(events)
    if not incoming.empty:
        incoming = incoming.copy()
        if "recorded_at" not in incoming.columns or incoming["recorded_at"].eq("").all():
            incoming["recorded_at"] = _now()
        incoming["recorded_by_run"] = incoming["recorded_by_run"].where(
            incoming["recorded_by_run"].astype(str).str.len() > 0,
            recorded_by_run,
        )

    existing = read_append_ledger(path, LIFECYCLE_COLUMNS)
    if existing.empty:
        merged = incoming
    elif incoming.empty:
        merged = existing
    else:
        known_ids = set(existing["event_id"].astype(str))
        novel = incoming[~incoming["event_id"].astype(str).isin(known_ids)]
        merged = pd.concat([existing, novel], ignore_index=True)

    merged = merged.sort_values(["improvement_id", "timestamp", "recorded_at"]).reset_index(drop=True)
    merged.to_parquet(path, index=False)
    return merged


def canonical_events(ledger_dir: Path) -> pd.DataFrame:
    """Deduped observation set for derived views (first record per event_id wins)."""
    bootstrap_event_log(ledger_dir)
    path = ledger_dir / EVENT_LOG_FILE
    if not path.exists():
        legacy = ledger_dir / EVENT_SNAPSHOT_FILE
        if legacy.exists():
            return pd.read_parquet(legacy)
        return event_ledger([])
    frame = pd.read_parquet(path)
    if frame.empty:
        return event_ledger([])
    ordered = frame.sort_values(["event_id", "recorded_at", "timestamp"])
    return ordered.drop_duplicates(subset=["event_id"], keep="first").reset_index(drop=True)


def materialize_event_snapshot(ledger_dir: Path, canonical: pd.DataFrame) -> Path:
    path = ledger_dir / EVENT_SNAPSHOT_FILE
    canonical.to_parquet(path, index=False)
    return path


def read_lifecycle_ledger(ledger_dir: Path) -> pd.DataFrame:
    return read_append_ledger(ledger_dir / LIFECYCLE_LEDGER_FILE, LIFECYCLE_COLUMNS)


def _event_columns() -> list[str]:
    return [
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
