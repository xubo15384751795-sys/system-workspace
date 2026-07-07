from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from .schemas import ACTIVE_DECISION_IMPACTS, PASSIVE_DECISION_IMPACTS, WEAK_ACTIVE_DECISION_IMPACTS


@dataclass(frozen=True)
class GovernanceArtifact:
    artifact_id: str
    artifact_type: str
    consumer: str | None
    decision_impact: str | None
    status: str
    risk_level: str


def classify_artifact(artifact: dict[str, Any]) -> str:
    """Classify an artifact as ALIVE, ALIVE_WEAK, PASSIVE, ZOMBIE, or DECORATIVE.

    Classification is based on consumer presence and decision_impact type.
    ZOMBIE = no consumer and no impact; ALIVE = active impacts; PASSIVE = warn/display.
    """
    consumer = artifact.get("consumer")
    impact = artifact.get("decision_impact")
    if consumer is None and impact in (None, "NONE"):
        return "ZOMBIE"
    if impact in ACTIVE_DECISION_IMPACTS:
        return "ALIVE"
    if impact in WEAK_ACTIVE_DECISION_IMPACTS:
        return "ALIVE_WEAK"
    if impact in PASSIVE_DECISION_IMPACTS:
        return "PASSIVE"
    return "DECORATIVE"


def risk_for_status(status: str) -> str:
    """Map artifact status to risk level: ZOMBIE→HIGH, PASSIVE/DECORATIVE→MEDIUM, else LOW."""
    if status == "ZOMBIE":
        return "HIGH"
    if status in {"PASSIVE", "DECORATIVE"}:
        return "MEDIUM"
    return "LOW"


def normalize_artifact(artifact: dict[str, Any]) -> GovernanceArtifact:
    """Normalize a raw artifact dict into a typed GovernanceArtifact with computed status and risk."""
    status = classify_artifact(artifact)
    return GovernanceArtifact(
        artifact_id=str(artifact.get("artifact_id") or artifact.get("artifact") or artifact.get("name")),
        artifact_type=str(artifact.get("artifact_type") or "UNKNOWN"),
        consumer=artifact.get("consumer"),
        decision_impact=artifact.get("decision_impact"),
        status=status,
        risk_level=str(artifact.get("risk_level") or risk_for_status(status)),
    )


def write_inventory(path: str | Path, artifacts: list[dict[str, Any]]) -> list[GovernanceArtifact]:
    """Normalize and write artifact inventory to JSON. Returns the normalized list."""
    normalized = [normalize_artifact(artifact) for artifact in artifacts]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(item) for item in normalized], indent=2) + "\n", encoding="utf-8")
    return normalized
