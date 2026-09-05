"""State trajectory hooks for dynamic diagnostics (not core scoring)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateTrajectory:
    """Time-ordered scalar pressure or state summaries for diagnostic use only."""

    times: tuple[float, ...]
    sigma_values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.times) != len(self.sigma_values):
            raise ValueError("times and sigma_values must have the same length")

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "times": list(self.times),
            "sigma_values": list(self.sigma_values),
        }
