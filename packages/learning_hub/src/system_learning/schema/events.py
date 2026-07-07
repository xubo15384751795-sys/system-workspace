from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from system_learning.schema import GovernanceMode, Severity, SystemEvent

GovernanceEventKind = Literal[
    "system_observation",
    "violation_group",
    "improvement_lifecycle",
    "governance_edge",
    "health_snapshot",
]


class SystemObservationEvent(SystemEvent):
    """Canonical runtime observation ingested from the Hub-owned log."""

    kind: GovernanceEventKind = "system_observation"


class ImprovementLifecycleEvent(BaseModel):
    """Append-only lifecycle transition; state is derived from the event stream."""

    model_config = ConfigDict(extra="allow")

    kind: GovernanceEventKind = "improvement_lifecycle"
    event_id: str
    improvement_id: str
    transition: str
    timestamp: str
    recorded_by_run: str = ""
    actor: str = ""
    notes: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class GovernanceEdgeEvent(BaseModel):
    """Derived sparse propagation edge (interpretation layer, not source of truth)."""

    model_config = ConfigDict(extra="allow")

    kind: GovernanceEventKind = "governance_edge"
    edge_id: str
    source_issue_family: str
    target_issue_family: str
    edge_type: str
    confidence: Literal["low", "medium", "high"] = "medium"
    rationale: str = ""
    source_subsystem: str = ""
    target_subsystem: str = ""
    supporting_event_ids: list[str] = Field(default_factory=list)


class ViolationGroupView(BaseModel):
    """Derived recurrence grouping over observations (materialized view, not mutable truth)."""

    kind: GovernanceEventKind = "violation_group"
    violation_id: str
    issue_family: str
    subsystem: str
    event_type: str
    severity: Severity = "info"
    recurrence_count: int = 0
    governance_mode: GovernanceMode = "observe_only"


class HealthSnapshotView(BaseModel):
    """Derived subsystem health (materialized view)."""

    kind: GovernanceEventKind = "health_snapshot"
    subsystem: str
    health_score: int = 100
    health_band: str = "healthy"
    event_count: int = 0
    violation_count: int = 0
