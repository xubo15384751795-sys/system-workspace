from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UTC = timezone.utc

SCHEMA_VERSION = "system_event.v1"

EVENT_FIELDS = [
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

SEVERITIES = ["info", "low", "medium", "high", "critical"]
CONFIDENCE_LEVELS = ["low", "medium", "high"]
GOVERNANCE_MODES = [
    "observe_only",
    "manual_review_required",
    "proposal_required",
    "auto_check_allowed",
    "blocker",
]


Severity = Literal["info", "low", "medium", "high", "critical"]
Confidence = Literal["low", "medium", "high"]
GovernanceMode = Literal[
    "observe_only",
    "manual_review_required",
    "proposal_required",
    "auto_check_allowed",
    "blocker",
]


class SystemEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = ""
    timestamp: str = ""
    subsystem: str = "unknown"
    event_type: str = "unspecified"
    severity: Severity = "info"
    source_tool: str = ""
    context_type: str = "unknown"
    confidence: Confidence = "medium"
    boundary_type: str = ""
    target_subsystem: str = ""
    related_paths: list[str] = Field(default_factory=list)
    governance_mode: GovernanceMode = "observe_only"
    run_id: str = ""
    bundle_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    recommended_action: str = ""
    source_report_path: str = ""
    requires_manual_review: bool = False

    @field_validator(
        "event_id",
        "timestamp",
        "subsystem",
        "event_type",
        "source_tool",
        "context_type",
        "boundary_type",
        "target_subsystem",
        "run_id",
        "bundle_id",
        "recommended_action",
        "source_report_path",
        mode="before",
    )
    @classmethod
    def coerce_string_fields(cls, value: Any) -> str:
        return none_to_empty(value).strip()

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, value: Any) -> str:
        return normalize_severity(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, value: Any) -> str:
        return normalize_confidence(value)

    @field_validator("governance_mode", mode="before")
    @classmethod
    def validate_governance_mode(cls, value: Any) -> str:
        return normalize_governance_mode(value)

    @field_validator("related_paths", mode="before")
    @classmethod
    def validate_related_paths(cls, value: Any) -> list[str]:
        return normalize_related_paths(value, None)

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        return {"value": value}

    @model_validator(mode="after")
    def assign_event_id(self) -> SystemEvent:
        if not self.event_id:
            self.event_id = stable_event_id(self.model_dump())
        return self


def normalize_event(raw_event: dict[str, Any], source_path: Path | None = None) -> dict[str, Any]:
    event = dict(raw_event)
    payload = event.get("payload")
    extras = {k: v for k, v in event.items() if k not in EVENT_FIELDS}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    if extras:
        payload = {**payload, "source_extra_fields": extras}

    normalized = {
        "event_id": event.get("event_id"),
        "timestamp": event.get("timestamp") or stable_timestamp(source_path),
        "subsystem": str(event.get("subsystem") or infer_subsystem_from_path(source_path)).strip(),
        "event_type": str(event.get("event_type") or "unspecified").strip(),
        "severity": normalize_severity(event.get("severity")),
        "source_tool": none_to_empty(event.get("source_tool")),
        "context_type": str(event.get("context_type") or infer_context_from_path(source_path)).strip(),
        "confidence": normalize_confidence(event.get("confidence")),
        "boundary_type": none_to_empty(event.get("boundary_type")),
        "target_subsystem": none_to_empty(event.get("target_subsystem")),
        "related_paths": normalize_related_paths(event.get("related_paths"), source_path),
        "governance_mode": normalize_governance_mode(event.get("governance_mode")),
        "run_id": none_to_empty(event.get("run_id")),
        "bundle_id": none_to_empty(event.get("bundle_id")),
        "payload": payload,
        "recommended_action": none_to_empty(event.get("recommended_action")),
        "source_report_path": str(event.get("source_report_path") or source_path or ""),
        "requires_manual_review": bool(event.get("requires_manual_review", False)),
    }
    return SystemEvent.model_validate(normalized).model_dump()


def normalize_severity(value: Any) -> str:
    severity = str(value or "info").strip().lower()
    if severity in {"warning", "warn"}:
        return "medium"
    if severity in {"error", "failure", "fail"}:
        return "high"
    if severity == "red":
        return "critical"
    if severity == "amber":
        return "high"
    return severity if severity in SEVERITIES else "info"


def normalize_confidence(value: Any) -> str:
    confidence = str(value or "medium").strip().lower()
    return confidence if confidence in CONFIDENCE_LEVELS else "medium"


def normalize_governance_mode(value: Any) -> str:
    mode = str(value or "observe_only").strip().lower()
    return mode if mode in GOVERNANCE_MODES else "observe_only"


def normalize_related_paths(value: Any, source_path: Path | None) -> list[str]:
    if value is None:
        return [str(source_path)] if source_path else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


def stable_event_id(event: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "timestamp": event.get("timestamp"),
            "subsystem": event.get("subsystem"),
            "event_type": event.get("event_type"),
            "run_id": event.get("run_id"),
            "bundle_id": event.get("bundle_id"),
            "source_report_path": event.get("source_report_path"),
            "payload": event.get("payload"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def stable_timestamp(path: Path | None) -> str:
    if path and path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z")
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def infer_subsystem_from_path(path: Path | None) -> str:
    if not path:
        return "unknown"
    lowered = str(path).lower()
    if "deformation" in lowered:
        return "deformation"
    if "harvester" in lowered:
        return "harvester"
    if "/ui/" in lowered or "interface" in lowered:
        return "ui"
    if "claim" in lowered or "paper" in lowered:
        return "paper_claim_guardian"
    return "unknown"


def infer_context_from_path(path: Path | None) -> str:
    if not path:
        return "unknown"
    lowered = str(path).lower()
    if "/tests/" in lowered or lowered.endswith("_test.py") or "test_" in Path(lowered).name:
        return "test_code"
    if "/docs/" in lowered or path.suffix.lower() in {".md", ".rst", ".txt"}:
        return "documentation"
    if "/archive/" in lowered:
        return "archive"
    if "/scripts/" in lowered:
        return "script"
    if "generated" in lowered:
        return "generated_file"
    return "production_code"


def none_to_empty(value: Any) -> str:
    return "" if value is None else str(value)
