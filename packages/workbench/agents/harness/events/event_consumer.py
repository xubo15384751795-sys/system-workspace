"""event_consumer — formal consumption protocol for event → Learning Hub ingestion.

Protocol (immutable contract):
  WHERE:  Output/system_learning/runtime/
  FORMAT: JSONL (JSON Lines, one normalized record per line)
  FILE:   records_{YYYY-MM-DD}.jsonl (Hub-owned runtime log)
  SCHEMA: See schema.yaml for event type definitions
  TRIGGER: Explicit consume() call (pull model), can be invoked:
           - Periodically by a system-tick / cron
           - On-demand via CLI
           - After a batch of writes

Cursor-based tracking prevents re-processing already-consumed events.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
def _resolve_system_root(workbench_root: Path) -> Path:
    """Repo root for both legacy `Workbench/` and `packages/workbench` layouts."""
    parent = workbench_root.parent
    if workbench_root.name.lower() == "workbench" and parent.name == "packages":
        return parent.parent
    return parent

SYSTEM_ROOT = _resolve_system_root(WORKBENCH_ROOT)
RUNTIME_DIR = SYSTEM_ROOT / "Output" / "system_learning" / "runtime"
CURSOR_DIR = RUNTIME_DIR / ".cursor"
CURSOR_FILE = CURSOR_DIR / "cursor.json"


# ── Protocol definition ─────────────────────────────────────────────────

@dataclass(frozen=True)
class ConsumptionProtocol:
    """Immutable contract defining HOW the Learning Hub reads events."""
    source_dir: Path = RUNTIME_DIR
    file_pattern: str = "records_*.jsonl"
    format: str = "jsonl"
    cursor_enabled: bool = True


PROTOCOL = ConsumptionProtocol()


# ── Cursor management ───────────────────────────────────────────────────

def _cursor_path(events_dir: Path | None = None) -> Path:
    """Return cursor file path, scoped to *events_dir* for test isolation."""
    root = events_dir or RUNTIME_DIR
    path = root / ".cursor" / "cursor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_cursor(events_dir: Path | None = None) -> dict[str, int]:
    """Read cursor map {filename: byte_offset}."""
    path = _cursor_path(events_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: int(v) for k, v in data.items()}
    except (json.JSONDecodeError, ValueError, OSError):
        pass
    return {}


def _write_cursor(cursor: dict[str, int], events_dir: Path | None = None) -> None:
    path = _cursor_path(events_dir)
    path.write_text(
        json.dumps(cursor, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ── Event file discovery ────────────────────────────────────────────────

def _list_event_files(events_dir: Path | None = None) -> list[Path]:
    """Return sorted list of event JSONL files matching the protocol pattern."""
    root = events_dir or RUNTIME_DIR
    if not root.exists():
        return []
    return sorted(root.glob("events_*.jsonl"))


# ── Event consumption ───────────────────────────────────────────────────

def consume_new_events(
    *,
    reset: bool = False,
    events_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Read new (unconsumed) events from the event store.

    Uses a cursor file to track byte offsets per event file so that
    already-consumed events are not returned again.

    Parameters
    ----------
    reset : bool
        If True, ignore the cursor and re-read ALL events from the
        beginning of every file. The cursor is updated afterward.
    events_dir : Path | None
        Override the events directory (used in tests).

    Returns
    -------
    list[dict]
        List of new event dicts, ordered by file then by line.
    """
    root = events_dir or RUNTIME_DIR
    cursor = {} if reset else _read_cursor(events_dir=events_dir)

    files = _list_event_files(root)
    new_events: list[dict[str, Any]] = []
    updated_cursor: dict[str, int] = {}

    for f in files:
        fname = f.name
        offset = cursor.get(fname, 0)

        try:
            data = f.read_bytes()
        except OSError:
            continue

        # Skip if file hasn't grown since last read
        file_size = len(data)
        if offset >= file_size and not reset:
            updated_cursor[fname] = offset
            continue

        # Read only the new bytes
        raw = data[offset:]
        text = raw.decode("utf-8")

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if isinstance(ev, dict):
                    new_events.append(ev)
            except json.JSONDecodeError:
                continue

        updated_cursor[fname] = file_size

    # Persist updated cursor
    _write_cursor(updated_cursor, events_dir=events_dir)

    return new_events


# ── Event dispatch ──────────────────────────────────────────────────────

def dispatch_events(
    events: list[dict[str, Any]],
    *,
    subsystem_filter: str | None = None,
    min_severity: str | None = None,
) -> dict[str, Any]:
    """Route consumed events through Learning Hub analysis.

    Parameters
    ----------
    events : list[dict]
        Events to analyse.
    subsystem_filter : str | None
        Optional subsystem to filter by.
    min_severity : str | None
        Minimum severity level ('info', 'warning', 'error', 'critical').

    Returns
    -------
    dict
        Summary with counts by type, severity, and recurring denial analysis.
    """
    severity_order = {"debug": 0, "info": 1, "warning": 2, "error": 3, "critical": 4}

    # Apply filters
    filtered = events
    if subsystem_filter:
        filtered = [e for e in filtered if e.get("subsystem") == subsystem_filter]
    if min_severity:
        min_rank = severity_order.get(min_severity, 0)
        filtered = [e for e in filtered if severity_order.get(e.get("severity", "info"), 1) >= min_rank]

    # Count by type
    by_type: dict[str, int] = {}
    for e in filtered:
        et = e.get("event_type", "unknown")
        by_type[et] = by_type.get(et, 0) + 1

    # Count by severity
    by_severity: dict[str, int] = {}
    for e in filtered:
        sev = e.get("severity", "info")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Collect recurring denials via system_event_writer analysis
    from agents.harness.events.system_event_writer import query_recurring_denials

    recurring = query_recurring_denials(hours=24, threshold=3)
    recurring_items = []
    for item in recurring:
        recurring_items.append({
            "issue": item.issue,
            "subsystem": item.subsystem,
            "severity": item.severity,
            "priority": item.priority,
            "count": item.count,
            "proposed_action": item.proposed_action,
        })

    return {
        "total": len(filtered),
        "by_type": by_type,
        "by_severity": by_severity,
        "recurring_denials": recurring_items,
    }


def consume_and_dispatch(
    *,
    reset: bool = False,
    events_dir: Path | None = None,
    subsystem_filter: str | None = None,
    min_severity: str | None = None,
) -> dict[str, Any]:
    """Full pipeline: consume new events → dispatch through Learning Hub.

    One-call entry point for the consumption protocol.

    Returns
    -------
    dict
        Dispatch summary, or empty signal if no events.
    """
    events = consume_new_events(reset=reset, events_dir=events_dir)
    if not events:
        return {"events": [], "message": "No new events to consume."}

    summary = dispatch_events(
        events,
        subsystem_filter=subsystem_filter,
        min_severity=min_severity,
    )
    summary["events_consumed"] = len(events)
    return summary
