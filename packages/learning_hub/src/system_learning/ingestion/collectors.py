from __future__ import annotations

import json
from pathlib import Path

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
    return events


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


def read_excerpt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError as exc:
        return f"Unable to read report excerpt: {exc}"
