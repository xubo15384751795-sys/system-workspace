"""Bundled research note: signal cards plus temporal, mismatch, criticality, and provider views."""

from __future__ import annotations

from dataclasses import dataclass

from src.dynamic.criticality import CriticalityState
from src.dynamic.mismatch import MismatchMap
from src.dynamic.models import TemporalFrame
from src.dynamic.provider_integrity import ProviderIntegrityPanel
from src.dynamic.signal_card import SignalCard


@dataclass(frozen=True)
class ResearchNote:
    note_id: str
    title: str
    generated_at: str
    executive_summary: str
    signal_cards: list[SignalCard]
    temporal_frame: TemporalFrame
    mismatch_map: MismatchMap
    criticality: CriticalityState
    provider_integrity: ProviderIntegrityPanel
    scenario_paths: list[str]
    limitations: list[str]
    disclaimer: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "signal_cards", list(self.signal_cards))
        object.__setattr__(self, "scenario_paths", list(self.scenario_paths))
        object.__setattr__(self, "limitations", list(self.limitations))

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "note_id": self.note_id,
            "title": self.title,
            "generated_at": self.generated_at,
            "executive_summary": self.executive_summary,
            "signal_cards": [c.to_serializable_dict() for c in self.signal_cards],
            "temporal_frame": self.temporal_frame.to_serializable_dict(),
            "mismatch_map": self.mismatch_map.to_serializable_dict(),
            "criticality": self.criticality.to_serializable_dict(),
            "provider_integrity": self.provider_integrity.to_serializable_dict(),
            "scenario_paths": list(self.scenario_paths),
            "limitations": list(self.limitations),
            "disclaimer": self.disclaimer,
        }
