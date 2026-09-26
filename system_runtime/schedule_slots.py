"""Persistent idempotency for launchd scheduled slots.

The launchd calendar trigger is at-least-once: sleep/wake, a manual reload, or
two loaded agents can invoke the same calendar slot more than once. This
module keeps the boundary explicit and local. A unique ``slot_key`` prevents
two live processes from both entering the authoritative publisher, while a
dead owner can be reclaimed after a crash.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "system.scheduled_slot.v1"
DEFAULT_LABEL = "com.system.daily-run"
DEFAULT_CALENDAR = "XNYS"
_RETRYABLE_REASON_CODES = frozenset(
    {
        "REQUIRED_STEP_FAILED",
        "STEP_BLOCKED",
        "PUBLISH_NOT_COMMITTED",
        "ADMISSION_REJECTED",
        "TRANSACTION_FAILED",
        "TRANSACTION_ROLLED_BACK",
        "RECOVERY_REQUIRED",
        "MANDATORY_SINK_FAILED",
    }
)


@dataclass(frozen=True)
class SlotClaim:
    """Result of an atomic slot claim."""

    slot_key: str
    owner_id: str
    acquired: bool
    existing_owner_id: str | None = None
    existing_status: str | None = None
    reclaimed_owner_id: str | None = None

    @property
    def duplicate(self) -> bool:
        return not self.acquired


class ScheduleSessionError(RuntimeError):
    """Raised when a scheduled slot cannot be mapped to a completed session."""


class ScheduledSlotStore:
    """SQLite-backed scheduled-slot state machine."""

    def __init__(self, database: Path | str) -> None:
        self.database = Path(database).expanduser().resolve()

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database, timeout=30) as connection:
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_slots (
                    slot_key TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    owner_pid INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('claimed', 'completed', 'abandoned')),
                    claimed_at TEXT NOT NULL,
                    completed_at TEXT,
                    outcome_json TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schedule_store_meta(key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )
            connection.commit()

    def claim(
        self,
        slot_key: str,
        *,
        owner_id: str,
        owner_pid: int | None = None,
        now: datetime | None = None,
    ) -> SlotClaim:
        """Atomically claim a slot or return the existing claim."""
        if not slot_key.strip():
            raise ValueError("slot_key must not be empty")
        if not owner_id.strip():
            raise ValueError("owner_id must not be empty")
        pid = int(owner_pid if owner_pid is not None else os.getpid())
        claimed_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        self.initialize()

        with sqlite3.connect(self.database, timeout=30) as connection:
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_id, owner_pid, status FROM scheduled_slots WHERE slot_key = ?",
                (slot_key,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO scheduled_slots
                        (slot_key, owner_id, owner_pid, status, claimed_at)
                    VALUES (?, ?, ?, 'claimed', ?)
                    """,
                    (slot_key, owner_id, pid, claimed_at),
                )
                connection.commit()
                return SlotClaim(slot_key=slot_key, owner_id=owner_id, acquired=True)

            existing_owner, existing_pid, existing_status = str(row[0]), int(row[1]), str(row[2])
            if existing_status == "claimed" and not _process_is_alive(existing_pid):
                connection.execute(
                    "UPDATE scheduled_slots SET status = 'abandoned', completed_at = ? WHERE slot_key = ?",
                    (claimed_at, slot_key),
                )
                connection.execute(
                    """
                    UPDATE scheduled_slots
                    SET owner_id = ?, owner_pid = ?, status = 'claimed',
                        claimed_at = ?, completed_at = NULL, outcome_json = NULL
                    WHERE slot_key = ?
                    """,
                    (owner_id, pid, claimed_at, slot_key),
                )
                connection.commit()
                return SlotClaim(
                    slot_key=slot_key,
                    owner_id=owner_id,
                    acquired=True,
                    reclaimed_owner_id=existing_owner,
                )

            # A completed row is only idempotent when it represents an
            # authoritative commit.  Older runs recorded failed or
            # not-published outcomes as ``completed``; treating those as
            # permanently consumed made the next launchd wake silently skip
            # the repair opportunity.  Reclaim the same slot for a retry while
            # preserving the original run bundle as the audit record.
            if existing_status == "completed" and _outcome_needs_retry(connection, slot_key):
                connection.execute(
                    """
                    UPDATE scheduled_slots
                    SET owner_id = ?, owner_pid = ?, status = 'claimed',
                        claimed_at = ?, completed_at = NULL, outcome_json = NULL
                    WHERE slot_key = ? AND status = 'completed'
                    """,
                    (owner_id, pid, claimed_at, slot_key),
                )
                connection.commit()
                return SlotClaim(
                    slot_key=slot_key,
                    owner_id=owner_id,
                    acquired=True,
                    reclaimed_owner_id=existing_owner,
                )

            connection.commit()
            return SlotClaim(
                slot_key=slot_key,
                owner_id=owner_id,
                acquired=False,
                existing_owner_id=existing_owner,
                existing_status=existing_status,
            )

    def complete(
        self,
        slot_key: str,
        *,
        owner_id: str,
        outcome: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> bool:
        """Mark a claimed slot complete if this process owns it."""
        timestamp = (completed_at or datetime.now(UTC)).astimezone(UTC).isoformat()
        payload = json.dumps(outcome, sort_keys=True, ensure_ascii=False) if outcome is not None else None
        self.initialize()
        with sqlite3.connect(self.database, timeout=30) as connection:
            connection.execute("PRAGMA busy_timeout=30000")
            cursor = connection.execute(
                """
                UPDATE scheduled_slots
                SET status = 'completed', completed_at = ?, outcome_json = ?
                WHERE slot_key = ? AND owner_id = ? AND status = 'claimed'
                """,
                (timestamp, payload, slot_key, owner_id),
            )
            connection.commit()
            return cursor.rowcount == 1

    def get(self, slot_key: str) -> dict[str, Any] | None:
        """Return a serializable slot record for diagnostics/tests."""
        self.initialize()
        with sqlite3.connect(self.database, timeout=30) as connection:
            row = connection.execute(
                """
                SELECT slot_key, owner_id, owner_pid, status, claimed_at,
                       completed_at, outcome_json
                FROM scheduled_slots WHERE slot_key = ?
                """,
                (slot_key,),
            ).fetchone()
        if row is None:
            return None
        outcome = None
        if row[6]:
            try:
                outcome = json.loads(str(row[6]))
            except json.JSONDecodeError:
                outcome = {"status": "invalid_outcome_json"}
        return {
            "slot_key": row[0],
            "owner_id": row[1],
            "owner_pid": row[2],
            "status": row[3],
            "claimed_at": row[4],
            "completed_at": row[5],
            "outcome": outcome,
        }


def slot_key_for_date(slot_date: date, *, label: str = DEFAULT_LABEL) -> str:
    """Build a stable key for one local calendar slot."""
    normalized_label = label.strip() or DEFAULT_LABEL
    return f"{normalized_label}|{slot_date.isoformat()}"


def local_slot_key(*, label: str = DEFAULT_LABEL, now: datetime | None = None) -> str:
    """Build the current local-date key used by a launchd calendar trigger."""
    instant = (now or datetime.now().astimezone()).astimezone()
    return slot_key_for_date(instant.date(), label=label)


def completed_session_slot_key(
    *,
    label: str = DEFAULT_LABEL,
    now: datetime | None = None,
    calendar_name: str = DEFAULT_CALENDAR,
) -> str:
    """Build a slot key for the most recent completed exchange session.

    launchd is at-least-once and may wake after sleep or across a DST change.
    Using the completed session label instead of the machine's wall-clock date
    means weekend/non-session wakes and duplicate wake-ups converge on one
    identity. A missing calendar is an explicit error so the scheduler cannot
    silently publish on a weekday approximation.
    """
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        import exchange_calendars as xcals
        import pandas as pd

        calendar = xcals.get_calendar(calendar_name)
        candidate = calendar.date_to_session(pd.Timestamp(instant.date()), direction="previous")
        session_close = calendar.session_close(candidate).to_pydatetime().astimezone(instant.tzinfo)
        if session_close > instant:
            candidate = calendar.previous_session(candidate)
        return slot_key_for_date(candidate.date(), label=label)
    except Exception as exc:  # noqa: BLE001 - scheduler must fail closed
        raise ScheduleSessionError(
            f"completed exchange session unavailable: calendar={calendar_name}"
        ) from exc


def default_database(root: Path) -> Path:
    """Return the state DB path without creating it."""
    configured = os.environ.get("SYSTEM_SCHEDULE_STATE_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return root / "Output" / "state" / "runtime" / "schedule_slots.sqlite3"


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _outcome_needs_retry(connection: sqlite3.Connection, slot_key: str) -> bool:
    """Return whether a completed slot failed before authoritative publish."""
    row = connection.execute(
        "SELECT outcome_json FROM scheduled_slots WHERE slot_key = ?",
        (slot_key,),
    ).fetchone()
    if not row or not row[0]:
        # A legacy completed row without an outcome cannot prove that a
        # commit happened.  Prefer a bounded retry over a permanent skip.
        return True
    try:
        outcome = json.loads(str(row[0]))
    except (TypeError, json.JSONDecodeError):
        return True
    if not isinstance(outcome, dict):
        return True
    if outcome.get("publish_status") != "COMMITTED":
        return True
    if outcome.get("execution_status") not in (None, "SUCCESS"):
        return True
    reason_codes = outcome.get("reason_codes", [])
    if not isinstance(reason_codes, (list, tuple, set, frozenset)):
        # A malformed legacy outcome must not make the scheduler crash or
        # silently consume the slot; retry so the next run can repair it.
        return True
    return bool(_RETRYABLE_REASON_CODES.intersection(str(code) for code in reason_codes))
