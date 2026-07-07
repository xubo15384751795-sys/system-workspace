"""Temporal dynamic models — serializable, validated time structure for cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


def _parse_iso_date(s: str) -> date:
    return date.fromisoformat(s)


@dataclass(frozen=True)
class EventPhase:
    """One named phase within a case, with optional mechanism metadata."""

    name: str
    start: str
    end: str
    dominant_mechanism: str | None
    expected_resolution: str | None = None

    def __post_init__(self) -> None:
        if _parse_iso_date(self.start) > _parse_iso_date(self.end):
            raise ValueError(
                f"Phase {self.name!r}: start {self.start} must be on or before end {self.end}"
            )


@dataclass(frozen=True)
class TemporalFrame:
    """Full temporal scaffolding for a case: ordered, non-overlapping phases."""

    case_id: str
    phases: tuple[EventPhase, ...]
    event_speed: str
    required_resolution: str
    observation_lag_tolerance_days: int

    def __post_init__(self) -> None:
        if not isinstance(self.phases, tuple):
            object.__setattr__(self, "phases", tuple(self.phases))
        phases = self.phases
        names = [p.name for p in phases]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"Phase names must be unique; duplicates: {dupes!r}")

        dated = [(p, _parse_iso_date(p.start), _parse_iso_date(p.end)) for p in phases]
        for p, s, e in dated:
            if s > e:
                raise ValueError(
                    f"Phase {p.name!r}: start {p.start} must be on or before end {p.end}"
                )

        sorted_phases = sorted(dated, key=lambda x: (x[1], x[2], x[0].name))
        for i in range(len(sorted_phases) - 1):
            _, _s1, e1 = sorted_phases[i]
            p2, s2, _e2 = sorted_phases[i + 1]
            if s2 <= e1:
                raise ValueError(
                    f"Phases must not overlap: {sorted_phases[i][0].name!r} ends {e1.isoformat()} "
                    f"but {p2.name!r} starts {s2.isoformat()}"
                )

    def to_serializable_dict(self) -> dict[str, object]:
        """Plain dict suitable for JSON (lists / scalars only)."""
        return {
            "case_id": self.case_id,
            "phases": [
                {
                    "name": p.name,
                    "start": p.start,
                    "end": p.end,
                    "dominant_mechanism": p.dominant_mechanism,
                    "expected_resolution": p.expected_resolution,
                }
                for p in self.phases
            ],
            "event_speed": self.event_speed,
            "required_resolution": self.required_resolution,
            "observation_lag_tolerance_days": self.observation_lag_tolerance_days,
        }
