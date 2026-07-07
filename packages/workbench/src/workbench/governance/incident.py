"""Incident tracking for repeated critical findings.

When the same finding appears in decision traces repeatedly, it escalates
from a warning to an incident. Incidents are persisted to a JSONL ledger
and surfaced in governance observability summaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


INCIDENT_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
INCIDENT_STATUSES = {"OBSERVING", "OPEN", "ACKNOWLEDGED", "RESOLVED"}

# Severity-dependent escalation thresholds.
# CRITICAL repeated >= 2 → INCIDENT_REQUIRED (blocks promotion)
# HIGH repeated >= 3 → ACTION_REQUIRED
# MEDIUM/LOW repeated >= 5 → ACTION_REQUIRED
ESCALATION_RULES: dict[str, tuple[int, str]] = {
    "CRITICAL": (2, "BLOCK_PROMOTION"),
    "HIGH": (3, "ACTION_REQUIRED"),
    "MEDIUM": (5, "ACTION_REQUIRED"),
    "LOW": (5, "ACTION_REQUIRED"),
}


def escalation_threshold(severity: str) -> int:
    """Return the occurrence count at which *severity* triggers escalation."""
    return ESCALATION_RULES.get(severity.upper(), (5, "ACTION_REQUIRED"))[0]


def escalation_decision_impact(severity: str) -> str:
    """Return the decision impact (e.g. BLOCK_PROMOTION) when *severity* escalates."""
    return ESCALATION_RULES.get(severity.upper(), (5, "ACTION_REQUIRED"))[1]


@dataclass
class IncidentRecord:
    incident_id: str
    finding_type: str
    severity: str
    first_seen: str
    last_seen: str
    occurrence_count: int
    status: str
    owner: str | None
    resolution: str | None
    related_artifact: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "finding_type": self.finding_type,
            "severity": self.severity,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "occurrence_count": self.occurrence_count,
            "status": self.status,
            "owner": self.owner,
            "resolution": self.resolution,
            "related_artifact": self.related_artifact,
        }


def _fingerprint(finding: str, artifact: str | None = None) -> str:
    """Create a stable fingerprint for a finding+artifact pair."""
    import hashlib
    raw = f"{finding}|{artifact or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_incidents(path: str | Path) -> list[IncidentRecord]:
    """Load all incident records from a JSONL ledger file."""
    path = Path(path)
    if not path.exists():
        return []
    records: list[IncidentRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
                records.append(IncidentRecord(**data))
            except (json.JSONDecodeError, TypeError):
                continue
    return records


def write_incident(path: str | Path, record: IncidentRecord) -> None:
    """Write or update an incident record, consolidating by incident_id."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = load_incidents(path)
    replaced = False
    updated: list[IncidentRecord] = []
    for rec in records:
        if rec.incident_id == record.incident_id:
            updated.append(record)
            replaced = True
        else:
            updated.append(rec)
    if not replaced:
        updated.append(record)
    with path.open("w", encoding="utf-8") as handle:
        for rec in updated:
            handle.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")


def create_or_update_incident(
    path: str | Path,
    *,
    finding: str,
    severity: str,
    artifact: str | None = None,
    owner: str | None = None,
) -> IncidentRecord | None:
    """Auto-create incident when finding repeats above its severity threshold.

    CRITICAL >= 2 → INCIDENT_REQUIRED (BLOCK_PROMOTION)
    HIGH >= 3 → ACTION_REQUIRED
    MEDIUM/LOW >= 5 → ACTION_REQUIRED

    Always writes a durable observation record so occurrence counting survives restarts.
    Returns the incident record when threshold is crossed, None otherwise.
    """
    threshold = escalation_threshold(severity)
    fp = _fingerprint(finding, artifact)
    existing = load_incidents(path)

    # Find or create the tracking record
    current: IncidentRecord | None = None
    for rec in existing:
        if rec.incident_id == fp and rec.status != "RESOLVED":
            current = rec
            break

    if current is None:
        current = IncidentRecord(
            incident_id=fp,
            finding_type=finding,
            severity=severity,
            first_seen=_now_iso(),
            last_seen=_now_iso(),
            occurrence_count=0,
            status="OBSERVING",
            owner=None,
            resolution=None,
            related_artifact=artifact,
        )

    current.occurrence_count += 1
    current.last_seen = _now_iso()
    crossed = current.occurrence_count >= threshold

    if crossed and current.status == "OBSERVING":
        current.status = "OPEN"
        current.severity = severity
        current.owner = owner

    write_incident(path, current)
    return current if crossed else None


def list_open_incidents(path: str | Path) -> list[IncidentRecord]:
    """Return incidents with status OPEN (escalation threshold crossed)."""
    return [r for r in load_incidents(path) if r.status == "OPEN"]


def incident_summary_rows(path: str | Path) -> list[dict[str, Any]]:
    """Return non-resolved incidents as summary dicts for dashboard display."""
    incidents = load_incidents(path)
    return [
        {
            "incident_id": r.incident_id,
            "finding_type": r.finding_type,
            "severity": r.severity,
            "occurrence_count": r.occurrence_count,
            "status": r.status,
            "last_seen": r.last_seen,
        }
        for r in incidents
        if r.status != "RESOLVED"
    ]
