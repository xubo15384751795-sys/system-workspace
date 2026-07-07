"""Provider-level data integrity panel (schema only; overall_status is caller-supplied)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_CHECK_STATUS = frozenset({"pass", "warn", "fail"})
_PANEL_STATUS = frozenset({"strong", "medium", "weak", "failed"})


@dataclass(frozen=True)
class ProviderCheck:
    series: str
    provider: str
    status: Literal["pass", "warn", "fail"]
    issue: str | None
    frequency: str | None
    staleness_days: int | None
    provider_disagreement: float | None

    def __post_init__(self) -> None:
        if self.status not in _CHECK_STATUS:
            raise ValueError(f"status must be one of {sorted(_CHECK_STATUS)}; got {self.status!r}")

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "series": self.series,
            "provider": self.provider,
            "status": self.status,
            "issue": self.issue,
            "frequency": self.frequency,
            "staleness_days": self.staleness_days,
            "provider_disagreement": self.provider_disagreement,
        }


@dataclass(frozen=True)
class ProviderIntegrityPanel:
    case_id: str | None
    overall_status: Literal["strong", "medium", "weak", "failed"]
    checks: list[ProviderCheck]
    affected_signal_cards: list[str]
    interpretation: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", list(self.checks))
        object.__setattr__(self, "affected_signal_cards", list(self.affected_signal_cards))
        if self.overall_status not in _PANEL_STATUS:
            raise ValueError(
                f"overall_status must be one of {sorted(_PANEL_STATUS)}; got {self.overall_status!r}"
            )

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "overall_status": self.overall_status,
            "checks": [c.to_serializable_dict() for c in self.checks],
            "affected_signal_cards": list(self.affected_signal_cards),
            "interpretation": self.interpretation,
        }
