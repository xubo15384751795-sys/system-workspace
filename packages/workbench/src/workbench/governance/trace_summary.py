from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from .schemas import DECISION_IMPACTS


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of dicts. Returns empty list if file missing."""
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            rows.append(json.loads(text))
    return rows


def count_decision_impacts(events: list[dict[str, Any]]) -> dict[str, int]:
    """Count occurrences of each decision_impact type across all events."""
    counts = Counter(event.get("decision_impact", "NONE") for event in events)
    return {impact: counts.get(impact, 0) for impact in DECISION_IMPACTS}


def summarize_authority_events(events: list[dict[str, Any]]) -> dict[str, int]:
    """Summarize authority events: total checks, violations, and configs enabled."""
    return {
        "authority_checks": len(events),
        "authority_violations": sum(1 for event in events if event.get("event_type") == "AUTHORITY_VIOLATION"),
        "authority_configs_enabled": sum(
            1 for event in events if event.get("event_type") in {"AUTHORITY_CONFIG_ENABLED", "UNKNOWN_AUTHORITY_CONFIG_ENABLED"}
        ),
    }


def detect_recurrence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect repeated findings by (finding_type, artifact) fingerprint.

    Returns recurring findings with occurrence counts, ordered by count descending.
    """
    counts: Counter = Counter()
    for event in events:
        finding = str(event.get("finding") or event.get("finding_type") or event.get("event_type", ""))
        artifact = str(event.get("artifact") or event.get("artifact_type") or "")
        if finding or artifact:
            fp = hashlib.sha256(f"{finding}|{artifact}".encode()).hexdigest()[:12]
            counts[fp] += 1

    recurring: list[dict[str, Any]] = []
    for event in events:
        finding = str(event.get("finding") or event.get("finding_type") or event.get("event_type", ""))
        artifact = str(event.get("artifact") or event.get("artifact_type") or "")
        if not finding and not artifact:
            continue
        fp = hashlib.sha256(f"{finding}|{artifact}".encode()).hexdigest()[:12]
        if counts[fp] >= 2:
            existing = next((r for r in recurring if r["fingerprint"] == fp), None)
            if existing is not None:
                existing["occurrence_count"] = counts[fp]
            else:
                recurring.append({
                    "fingerprint": fp,
                    "finding_type": finding,
                    "artifact": artifact,
                    "occurrence_count": counts[fp],
                    "severity": event.get("severity", "UNKNOWN"),
                })
    return sorted(recurring, key=lambda r: r["occurrence_count"], reverse=True)


def summarize_trace_paths(
    *,
    decision_trace_path: str | Path,
    authority_trace_path: str | Path,
) -> dict[str, Any]:
    """Load and summarize both decision and authority trace files.

    Returns a dict with decision_impact_counts, authority summary, and
    recurring_findings.
    """
    decision_events = read_jsonl(decision_trace_path)
    authority_events = read_jsonl(authority_trace_path)
    return {
        "decision_impact_counts": count_decision_impacts(decision_events),
        "authority": summarize_authority_events(authority_events),
        "recurring_findings": detect_recurrence(decision_events),
    }
