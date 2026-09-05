from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConceptImplementationStatus(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class ProjectionStatus(str, Enum):
    NONE = "NONE"
    HEURISTIC_NOT_MEASUREMENT = "HEURISTIC_NOT_MEASUREMENT"


@dataclass(frozen=True)
class ConceptRegistryEntry:
    concept: str
    label: str
    status: ConceptImplementationStatus
    warning: str
    proxy: str | None = None
    projection_status: ProjectionStatus = ProjectionStatus.NONE
    do_not_interpret_as: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "concept": self.concept,
            "label": self.label,
            "status": self.status.value,
            "warning": self.warning,
            "proxy": self.proxy,
        }
        if self.projection_status is not ProjectionStatus.NONE:
            payload["projection_status"] = self.projection_status.value
        if self.do_not_interpret_as is not None:
            payload["do_not_interpret_as"] = self.do_not_interpret_as
        return payload


CONCEPT_REGISTRY: dict[str, ConceptRegistryEntry] = {
    "S": ConceptRegistryEntry(
        "S",
        "Subjects",
        ConceptImplementationStatus.NOT_IMPLEMENTED,
        "Subjects have no actor-level operational state in current code.",
        projection_status=ProjectionStatus.HEURISTIC_NOT_MEASUREMENT,
        do_not_interpret_as="S (Subjects)",
    ),
    "A": ConceptRegistryEntry(
        "A",
        "Anchors",
        ConceptImplementationStatus.PARTIAL,
        "Anchors are implicit inside M; current code cannot identify which anchor is failing.",
        proxy="M",
    ),
    "L": ConceptRegistryEntry(
        "L",
        "Liquidation paths",
        ConceptImplementationStatus.NOT_IMPLEMENTED,
        "Liquidation path trees are folded into D and are not separately measured.",
        proxy="D",
        projection_status=ProjectionStatus.HEURISTIC_NOT_MEASUREMENT,
        do_not_interpret_as="L (Liquidation paths)",
    ),
    "V": ConceptRegistryEntry(
        "V",
        "Verifiability density",
        ConceptImplementationStatus.NOT_IMPLEMENTED,
        "V is not proxied. V-to-X claims are not empirically supported by current code.",
        projection_status=ProjectionStatus.HEURISTIC_NOT_MEASUREMENT,
        do_not_interpret_as="V (Verifiability density)",
    ),
    "P": ConceptRegistryEntry(
        "P",
        "Positional power",
        ConceptImplementationStatus.PARTIAL,
        "Positional power is folded into operator penalty weights, not separately measured.",
    ),
    "tau": ConceptRegistryEntry(
        "tau",
        "Latency",
        ConceptImplementationStatus.NOT_IMPLEMENTED,
        "Latency is handled as data hygiene/lookahead discipline, not as a measured channel.",
        projection_status=ProjectionStatus.HEURISTIC_NOT_MEASUREMENT,
        do_not_interpret_as="tau (Latency)",
    ),
}


def concept_registry_payload() -> dict[str, dict[str, Any]]:
    return {key: entry.to_dict() for key, entry in CONCEPT_REGISTRY.items()}
