from __future__ import annotations

import json
from pathlib import Path

import yaml

from system_learning.schema import normalize_event

LEARNING_SUFFIXES = {".json", ".jsonl", ".md", ".txt"}


def collect_events(system_root: Path) -> list[dict]:
    events: list[dict] = []
    for path in event_file_paths(system_root):
        events.extend(read_jsonl_events(path))
    for path in ml_integrity_event_paths(system_root):
        events.extend(events_from_ml_integrity_json(path))
    for path in violation_report_paths(system_root):
        events.extend(events_from_violations_json(path))
    for path in learning_report_paths(system_root):
        events.append(event_from_learning_report(path))
    for path in checkpoint_paths(system_root):
        events.append(event_from_checkpoint(path))
    for path in routing_decision_paths(system_root):
        events.append(event_from_routing_decision(path))
    events.extend(events_from_open_threads(system_root / "governance" / "open_threads.yaml"))
    return events


def checkpoint_paths(system_root: Path) -> list[Path]:
    return sorted((system_root / ".cursor" / "checkpoints").glob("*.md"))


def routing_decision_paths(system_root: Path) -> list[Path]:
    return sorted((system_root / "Output" / "system_learning" / "routing_decisions").glob("*.yaml"))


def event_file_paths(system_root: Path) -> list[Path]:
    patterns = [
        "Output/system_learning/runtime/records_*.jsonl",
        "Output/system_learning/events/*.jsonl",
        "Output/deformation_runs/*/system_events.jsonl",
        "Data/harvester/exports/*/system_events.jsonl",
        "System Learning Hub/reports/codebase/latest/system_events.jsonl",
    ]
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(system_root.glob(pattern))
    return sorted(set(paths))


def ml_integrity_event_paths(system_root: Path) -> list[Path]:
    events_dir = system_root / "Output" / "system_learning" / "events"
    if not events_dir.exists():
        return []
    return sorted(
        path
        for path in events_dir.glob("ml_*.json")
        if path.is_file()
    )


def events_from_ml_integrity_json(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            normalize_event(
                {
                    "event_type": "malformed_ml_integrity_event",
                    "severity": "high",
                    "subsystem": "ml_integrity",
                    "payload": {"error": str(exc), "path": str(path)},
                    "recommended_action": "Repair the malformed ML integrity event file at source.",
                    "requires_manual_review": True,
                },
                path,
            )
        ]
    if not isinstance(raw, dict):
        raw = {"value": raw}
    event = dict(raw)
    if not event.get("source_report_path"):
        event["source_report_path"] = str(path)
    if event.get("requires_manual_review") is False and event.get("governance_mode") in {
        "manual_review_required",
        "proposal_required",
        "blocker",
    }:
        event["requires_manual_review"] = True
    return [normalize_event(event, path)]


def violation_report_paths(system_root: Path) -> list[Path]:
    return sorted(set(system_root.glob("**/reports/governance/*/violations.json")))


def learning_report_paths(system_root: Path) -> list[Path]:
    paths = []
    for path in system_root.glob("**/reports/learning/*"):
        if path.is_file() and path.suffix.lower() in LEARNING_SUFFIXES:
            paths.append(path)
    return sorted(set(paths))


def read_jsonl_events(path: Path) -> list[dict]:
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raw = {
                    "event_type": "malformed_system_event",
                    "severity": "high",
                    "payload": {"line_number": line_number, "error": str(exc), "raw_line": line[:500]},
                    "recommended_action": "Repair the malformed standardized event record at source.",
                    "requires_manual_review": True,
                }
            events.append(normalize_event(raw, path))
    return events


def events_from_violations_json(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            normalize_event(
                {
                    "event_type": "malformed_violation_report",
                    "severity": "high",
                    "payload": {"error": str(exc)},
                    "recommended_action": "Repair the malformed governance violations report at source.",
                    "source_report_path": str(path),
                    "requires_manual_review": True,
                },
                path,
            )
        ]

    records = data if isinstance(data, list) else data.get("violations", [data])
    events = []
    for record in records:
        if not isinstance(record, dict):
            record = {"value": record}
        events.append(
            normalize_event(
                {
                    "timestamp": record.get("timestamp"),
                    "subsystem": record.get("subsystem"),
                    "event_type": record.get("event_type") or record.get("violation_type") or "governance_violation",
                    "severity": record.get("severity", "medium"),
                    "run_id": record.get("run_id"),
                    "bundle_id": record.get("bundle_id"),
                    "payload": record,
                    "recommended_action": record.get("recommended_action", "Review governance violation recurrence."),
                    "source_report_path": str(path),
                    "requires_manual_review": True,
                },
                path,
            )
        )
    return events


def event_from_learning_report(path: Path) -> dict:
    excerpt = read_excerpt(path)
    return normalize_event(
        {
            "event_type": "learning_report_available",
            "severity": "info",
            "payload": {"report_excerpt": excerpt[:2000]},
            "recommended_action": "Review learning report and decide whether a manual improvement proposal is warranted.",
            "source_report_path": str(path),
            "requires_manual_review": False,
        },
        path,
    )


def event_from_checkpoint(path: Path) -> dict:
    excerpt = read_excerpt(path)
    return normalize_event(
        {
            "event_type": "governance_checkpoint",
            "subsystem": "learning_hub",
            "source_tool": "checkpoint_ingest",
            "context_type": "governance_memory",
            "confidence": "high",
            "payload": {"checkpoint_excerpt": excerpt[:4000]},
            "recommended_action": "Retain this checkpoint in governance memory and route its open work through the Hub improvement queue.",
            "source_report_path": str(path),
            "requires_manual_review": "open_thread" in excerpt.lower() or "next_agent_action" in excerpt.lower(),
        },
        path,
    )


def event_from_routing_decision(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raw = {"status": "malformed", "error": str(exc)}
    if not isinstance(raw, dict):
        raw = {"value": raw}
    status = str(raw.get("status") or "recorded").lower()
    return normalize_event(
        {
            "timestamp": _dated_document_timestamp(raw.get("date"), path),
            "event_type": f"routing_decision_{status}",
            "subsystem": "agent_routing",
            "target_subsystem": "learning_hub",
            "source_tool": "routing_decision_ingest",
            "context_type": "routing_decision",
            "confidence": "high",
            "payload": {
                "decision_id": raw.get("id") or path.stem,
                "title": raw.get("title", ""),
                "summary": raw.get("summary", ""),
                "artifacts": raw.get("artifacts", []),
                "acceptance": raw.get("acceptance", []),
                "status": status,
            },
            "recommended_action": "Preserve the routing decision as auditable governance memory.",
            "source_report_path": str(path),
            "requires_manual_review": status in {"proposed", "pending", "malformed"},
        },
        path,
    )


def events_from_open_threads(path: Path) -> list[dict]:
    """Migrate the former WB-D queue into Hub-owned improvement events."""
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    threads = raw.get("threads", []) if isinstance(raw, dict) else []
    events = []
    for thread in threads:
        if not isinstance(thread, dict) or str(thread.get("status", "open")).lower() == "done":
            continue
        thread_id = str(thread.get("id") or "unnamed")
        priority = str(thread.get("priority") or "MEDIUM").upper()
        events.append(
            normalize_event(
                {
                    "timestamp": _dated_document_timestamp(raw.get("updated"), path),
                    "event_type": f"governance_open_thread_{thread_id}",
                    "subsystem": str(thread.get("module") or "governance"),
                    "target_subsystem": "learning_hub",
                    "source_tool": "open_threads_migration",
                    "context_type": "governance_work_item",
                    "severity": "high" if priority == "HIGH" else "medium",
                    "governance_mode": "proposal_required" if priority == "HIGH" else "manual_review_required",
                    "payload": {
                        "thread_id": thread_id,
                        "reason": thread.get("reason", ""),
                        "command": thread.get("command", ""),
                        "priority": priority,
                        "migrated_from": "governance/open_threads.yaml",
                    },
                    "recommended_action": str(thread.get("action") or "Review the migrated governance work item."),
                    "source_report_path": str(path),
                    "requires_manual_review": True,
                },
                path,
            )
        )
    return events


def _dated_document_timestamp(value: object, path: Path) -> str:
    text = str(value or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text}T00:00:00Z"
    return normalize_event({}, path)["timestamp"]


def read_excerpt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError as exc:
        return f"Unable to read report excerpt: {exc}"
