from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Literal


DecisionImpact = Literal[
    "BLOCK",
    "QUARANTINE",
    "DOWNWEIGHT",
    "PROMOTE",
    "ACTION_REQUIRED",
    "WARN_ONLY",
    "DISPLAY_ONLY",
    "NONE",
]
VALID_DECISION_IMPACTS = {
    "BLOCK",
    "QUARANTINE",
    "DOWNWEIGHT",
    "PROMOTE",
    "ACTION_REQUIRED",
    "WARN_ONLY",
    "DISPLAY_ONLY",
    "NONE",
}


@dataclass(frozen=True)
class DecisionEvent:
    run_id: str
    artifact: str
    artifact_type: str
    finding: str
    decision_impact: DecisionImpact
    consumer: str | None
    severity: str
    reason: str
    ts: float


def validate_decision_event(event: DecisionEvent) -> None:
    """Validate a decision event's structural constraints.

    Raises ValueError if: invalid decision_impact, non-NONE impact missing
    consumer, blocking impacts with low severity, or empty reason.
    """
    if event.decision_impact not in VALID_DECISION_IMPACTS:
        raise ValueError(f"Invalid decision_impact: {event.decision_impact}")
    if event.decision_impact != "NONE" and not event.consumer:
        raise ValueError(f"{event.decision_impact} decision requires a consumer")
    if event.decision_impact in {"BLOCK", "QUARANTINE", "DOWNWEIGHT", "ACTION_REQUIRED"}:
        if event.severity in {"", "OK", "LOW"}:
            raise ValueError(f"{event.decision_impact} decision requires non-low severity")
    if not event.reason.strip():
        raise ValueError("Decision event requires a reason")


def append_decision_event(path: str | Path, event: DecisionEvent) -> None:
    """Validate and append a decision event to the JSONL trace file.

    Writes artifacts — creates parent directories if needed.
    """
    validate_decision_event(event)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")


def record_decision(
    path: str | Path,
    *,
    run_id: str,
    artifact: str,
    artifact_type: str,
    finding: str,
    decision_impact: DecisionImpact,
    consumer: str | None,
    severity: str,
    reason: str,
) -> None:
    """Convenience wrapper — build a DecisionEvent and append it to the trace.

    Writes artifacts to the JSONL file at *path*.
    """
    event = DecisionEvent(
        run_id=run_id,
        artifact=artifact,
        artifact_type=artifact_type,
        finding=finding,
        decision_impact=decision_impact,
        consumer=consumer,
        severity=severity,
        reason=reason,
        ts=time.time(),
    )
    append_decision_event(path, event)
