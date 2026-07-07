"""Transition-oriented diagnostic signals (not core scoring; not probabilities)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransitionSignal:
    """Optional trajectory / rate diagnostics for dynamic criticality views.

    Fields are interpretive summaries of change pressure, not transition probabilities.
    """

    pressure_slope: float | None = None
    mode_coupling_index: float | None = None

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "pressure_slope": self.pressure_slope,
            "mode_coupling_index": self.mode_coupling_index,
        }
