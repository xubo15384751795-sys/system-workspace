"""Human-facing signal cards for dynamic diagnostics (schema only; no Pydantic)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_SIGNAL_STATUS = frozenset({"inactive", "watch", "warning", "critical"})
_SIGNAL_SEVERITY = frozenset({"low", "medium", "high", "critical"})
_SIGNAL_CONFIDENCE = frozenset({"low", "medium", "high"})
_EVIDENCE_RELIABILITY = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class EvidenceItem:
    source: str
    metric: str
    value: float | str
    timestamp: str | None
    reliability: Literal["high", "medium", "low"]

    def __post_init__(self) -> None:
        if self.reliability not in _EVIDENCE_RELIABILITY:
            raise ValueError(
                f"reliability must be one of {sorted(_EVIDENCE_RELIABILITY)}; got {self.reliability!r}"
            )

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "metric": self.metric,
            "value": self.value,
            "timestamp": self.timestamp,
            "reliability": self.reliability,
        }


@dataclass(frozen=True)
class SignalCard:
    signal_id: str
    title: str
    status: Literal["inactive", "watch", "warning", "critical"]
    severity: Literal["low", "medium", "high", "critical"]
    confidence: Literal["low", "medium", "high"]
    time_window: str
    phase: str | None
    main_trigger: list[str]
    affected_dimensions: list[str]
    path_interpretation: str
    evidence: list[EvidenceItem]
    user_action: list[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "main_trigger", list(self.main_trigger))
        object.__setattr__(self, "affected_dimensions", list(self.affected_dimensions))
        object.__setattr__(self, "evidence", list(self.evidence))
        object.__setattr__(self, "user_action", list(self.user_action))
        if self.status not in _SIGNAL_STATUS:
            raise ValueError(f"status must be one of {sorted(_SIGNAL_STATUS)}; got {self.status!r}")
        if self.severity not in _SIGNAL_SEVERITY:
            raise ValueError(
                f"severity must be one of {sorted(_SIGNAL_SEVERITY)}; got {self.severity!r}"
            )
        if self.confidence not in _SIGNAL_CONFIDENCE:
            raise ValueError(
                f"confidence must be one of {sorted(_SIGNAL_CONFIDENCE)}; got {self.confidence!r}"
            )

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "signal_id": self.signal_id,
            "title": self.title,
            "status": self.status,
            "severity": self.severity,
            "confidence": self.confidence,
            "time_window": self.time_window,
            "phase": self.phase,
            "main_trigger": list(self.main_trigger),
            "affected_dimensions": list(self.affected_dimensions),
            "path_interpretation": self.path_interpretation,
            "evidence": [e.to_serializable_dict() for e in self.evidence],
            "user_action": list(self.user_action),
        }
