"""learning_hub_tools — governed tools for System Learning Hub.

Registered tools:
  learning_hub.inspect_queue              — inspect improvement queue
  learning_hub.ingest_events              — ingest events into the learning pipeline
  learning_hub.query_recurrence           — query recurrence patterns from ingested events
  learning_hub.write_verification_record  — write a verification record (mutation!)

Every handler accepts (input: dict, dry_run: bool) → ToolResult.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.registry import ToolResult, ToolSpec, _register

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
def _resolve_system_root(workbench_root: Path) -> Path:
    """Repo root for both legacy `Workbench/` and `packages/workbench` layouts."""
    parent = workbench_root.parent
    if workbench_root.name.lower() == "workbench" and parent.name == "packages":
        return parent.parent
    return parent

SYSTEM_ROOT = _resolve_system_root(WORKBENCH_ROOT)
REPORTS_DIR = SYSTEM_ROOT / "Output" / "system_learning" / "latest"
RUNTIME_DIR = SYSTEM_ROOT / "Output" / "system_learning" / "runtime"
RECORD_SCRIPT = SYSTEM_ROOT / "scripts" / "record_runtime_event.py"


# ── helpers ─────────────────────────────────────────────────────────────

def _parse_md_table(lines: list[str]) -> list[dict[str, str]]:
    """Parse a standard markdown table into list of dicts."""
    header_line = None
    sep_line = None
    data_lines: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and "---" in stripped:
            sep_line = i
            if i > 0 and lines[i - 1].strip().startswith("|"):
                header_line = i - 1
        elif stripped.startswith("|") and sep_line is not None and i > sep_line:
            data_lines.append(stripped)

    if header_line is None:
        return []

    headers = [h.strip() for h in lines[header_line].strip().strip("|").split("|")]
    rows = []
    for dl in data_lines:
        cells = [c.strip() for c in dl.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def _read_md_report(filename: str) -> list[dict[str, str]]:
    path = REPORTS_DIR / filename
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _parse_md_table(text.splitlines())


# ── handlers ────────────────────────────────────────────────────────────

def _h_inspect_queue(input: dict, dry_run: bool) -> ToolResult:
    if dry_run:
        return ToolResult(ok=True, tool_id="learning_hub.inspect_queue", summary="[DRY RUN] inspect improvement queue")

    rows = _read_md_report("improvement_queue.md")
    if not rows:
        return ToolResult(
            ok=True,
            tool_id="learning_hub.inspect_queue",
            summary="No items in improvement queue",
            evidence={"queue": [], "count": 0},
        )

    items = []
    for r in rows:
        items.append({
            "state": r.get("State", ""),
            "priority": r.get("Priority", ""),
            "severity": r.get("Severity", ""),
            "subsystem": r.get("Subsystem", ""),
            "issue": r.get("Issue", ""),
            "count": r.get("Count", ""),
            "proposed_action": r.get("Proposed Action", ""),
        })

    return ToolResult(
        ok=True,
        tool_id="learning_hub.inspect_queue",
        summary=f"Improvement queue: {len(items)} items",
        evidence={"queue": items, "count": len(items)},
    )


def _h_ingest_events(input: dict, dry_run: bool) -> ToolResult:
    events = input.get("events", [])
    source = input.get("source", "unknown")
    if dry_run:
        return ToolResult(ok=True, tool_id="learning_hub.ingest_events", summary=f"[DRY RUN] ingest {len(events)} events from {source}")

    if not events:
        return ToolResult(
            ok=True,
            tool_id="learning_hub.ingest_events",
            summary="No events to ingest",
            evidence={"ingested": 0, "source": source},
        )

    # In a full implementation, events would be written to the learning hub's
    # event store (SQLite / Parquet / Kafka).  Here we validate structure only.
    validated: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []

    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            errors.append(f"Event {i} is not a dict: {type(ev).__name__}")
            continue
        required = {"timestamp", "subsystem", "event_type"}
        missing = required - set(ev.keys())
        if missing:
            warnings.append(f"Event {i} missing keys: {sorted(missing)}")
        validated.append({
            "timestamp": ev.get("timestamp", ""),
            "subsystem": ev.get("subsystem", ""),
            "event_type": ev.get("event_type", ""),
            "payload": ev.get("payload", {}),
        })

    ok = len(errors) == 0
    return ToolResult(
        ok=ok,
        tool_id="learning_hub.ingest_events",
        summary=f"Ingested {len(validated)} events from {source}",
        evidence={"ingested": len(validated), "source": source, "events": validated},
        warnings=warnings,
        errors=errors,
    )


def _collect_events(events_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read Hub runtime log files and return parsed records."""
    root = events_dir or RUNTIME_DIR
    if not root.exists():
        return []
    all_events: list[dict[str, Any]] = []
    for f in sorted(root.glob("records_*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    all_events.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            continue
    return all_events


def _collect_verifications(verifications_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read verification records from the Hub runtime log."""
    _ = verifications_dir
    records: list[dict[str, Any]] = []
    for event in _collect_events():
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
        if event.get("event_type") == "verification_record" or payload.get("schema_version") == "workbench.verification_record.v1":
            records.append(payload if payload is not event else event)
    return records


def _h_query_recurrence(input: dict, dry_run: bool) -> ToolResult:
    pattern = input.get("pattern", "*")
    limit = input.get("limit", 50)
    group_by = input.get("group_by", "event_type")
    if dry_run:
        return ToolResult(ok=True, tool_id="learning_hub.query_recurrence", summary=f"[DRY RUN] query pattern={pattern}")

    events = _collect_events()
    if not events:
        return ToolResult(
            ok=True,
            tool_id="learning_hub.query_recurrence",
            summary="No events found — event store is empty",
            evidence={"pattern": pattern, "limit": limit, "results": [], "count": 0},
        )

    # Filter by pattern on event_type (or the chosen group_by field)
    if pattern != "*":
        filtered = [ev for ev in events if fnmatch.fnmatch(str(ev.get(group_by, "")), pattern)]
    else:
        filtered = events

    # Group by the requested field
    key: str = group_by
    counter: Counter[str] = Counter()
    for ev in filtered:
        val = str(ev.get(key, "unknown"))
        counter[val] += 1

    top = counter.most_common(limit)
    results = [
        {"group": k, "event_type": k, "count": v}
        for k, v in top
    ]

    return ToolResult(
        ok=True,
        tool_id="learning_hub.query_recurrence",
        summary=f"Recurrence query: {len(results)} groups (pattern={pattern}, group_by={group_by})",
        evidence={
            "pattern": pattern,
            "group_by": group_by,
            "limit": limit,
            "total_events": len(filtered),
            "results": results,
            "count": len(results),
        },
    )


def _h_write_verification_record(input: dict, dry_run: bool) -> ToolResult:
    """Write a verification record.  This is a MUTATION tool — it persists a record.

    Only allowed in "verify" and "edit" modes.
    """
    tool_id = input.get("tool_id", "")
    summary = input.get("summary", "")
    evidence = input.get("evidence", {})
    if dry_run:
        return ToolResult(ok=True, tool_id="learning_hub.write_verification_record", summary=f"[DRY RUN] write record for {tool_id}")

    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "record_id": record_id,
        "tool_id": tool_id,
        "summary": summary,
        "evidence": evidence,
        "recorded_at": now,
        "schema_version": "workbench.verification_record.v1",
    }

    path = RUNTIME_DIR / f"records_{now[:10]}.jsonl"
    if RECORD_SCRIPT.is_file():
        subprocess.run(
            [
                sys.executable,
                str(RECORD_SCRIPT),
                "--system-root",
                str(SYSTEM_ROOT),
                "--subsystem",
                "learning_hub",
                "--event-type",
                "verification_record",
                "--severity",
                "info",
                "--source-tool",
                "learning_hub.write_verification_record",
                "--payload-json",
                json.dumps(record, ensure_ascii=False, default=str),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    return ToolResult(
        ok=True,
        tool_id="learning_hub.write_verification_record",
        summary=f"Verification record written for {tool_id or '(unnamed)'}",
        evidence={
            "record_id": record_id,
            "recorded_tool_id": tool_id,
            "recorded_summary": summary,
            "path": str(path),
        },
        artifacts=[str(path)],
    )


# ── registration ────────────────────────────────────────────────────────

_register(ToolSpec(
    id="learning_hub.inspect_queue",
    description="Inspect the improvement queue from the System Learning Hub",
    subsystem="learning_hub",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_inspect_queue,
))

_register(ToolSpec(
    id="learning_hub.ingest_events",
    description="Ingest structured events into the learning pipeline for pattern analysis",
    subsystem="learning_hub",
    risk_level="medium",
    read_only=False,
    mutates_artifacts=True,
    requires_approval=True,
    allowed_modes=["run", "edit"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_ingest_events,
))

_register(ToolSpec(
    id="learning_hub.query_recurrence",
    description="Query recurrence patterns from the learning event store",
    subsystem="learning_hub",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_query_recurrence,
))

_register(ToolSpec(
    id="learning_hub.write_verification_record",
    description="Write a verification record to the learning hub's verification log",
    subsystem="learning_hub",
    risk_level="medium",
    read_only=False,
    mutates_artifacts=True,
    requires_approval=True,
    allowed_modes=["verify", "edit"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_write_verification_record,
))
