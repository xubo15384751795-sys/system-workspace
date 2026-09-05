"""Criticality diagnostic state and adapter over existing singular/threshold inputs (diagnostic-only)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.dynamic.transition import TransitionSignal
from src.dynamic.trajectory import StateTrajectory

if TYPE_CHECKING:
    from src.derivation.singular_detector import SingularDetectionDiagnostics

_CRITICALITY_STATUS = frozenset({"safe", "watch", "near_threshold", "crossed", "unknown"})


def _clip_unit(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


@dataclass(frozen=True)
class CriticalityState:
    case_id: str | None
    status: str
    nearest_threshold: str | None
    distance_to_threshold: float | None
    crossed_conditions: list[str]
    transition_candidate: bool
    level_risk: float | None
    transition_risk: float | None
    evidence: list[str]
    interpretation: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "crossed_conditions", list(self.crossed_conditions))
        object.__setattr__(self, "evidence", list(self.evidence))
        if self.status not in _CRITICALITY_STATUS:
            raise ValueError(
                f"status must be one of {sorted(_CRITICALITY_STATUS)}; got {self.status!r}"
            )
        if self.distance_to_threshold is not None and self.distance_to_threshold < 0:
            raise ValueError("distance_to_threshold must be None or non-negative")
        for name, val in (("level_risk", self.level_risk), ("transition_risk", self.transition_risk)):
            if val is not None and not (0.0 <= val <= 1.0):
                raise ValueError(f"{name} must be None or in [0, 1]")

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "nearest_threshold": self.nearest_threshold,
            "distance_to_threshold": self.distance_to_threshold,
            "crossed_conditions": list(self.crossed_conditions),
            "transition_candidate": self.transition_candidate,
            "level_risk": self.level_risk,
            "transition_risk": self.transition_risk,
            "evidence": list(self.evidence),
            "interpretation": self.interpretation,
        }


def _transition_risk_from_signal(signal: TransitionSignal | None) -> float | None:
    if signal is None:
        return None
    parts: list[float] = []
    if signal.pressure_slope is not None:
        parts.append(_clip_unit(abs(float(signal.pressure_slope))))
    if signal.mode_coupling_index is not None:
        parts.append(_clip_unit(abs(float(signal.mode_coupling_index))))
    if not parts:
        return None
    return max(parts)


def _transition_risk_from_trajectory(
    trajectory: StateTrajectory | None,
    sigma_threshold: float,
) -> float | None:
    if trajectory is None or len(trajectory.sigma_values) < 2:
        return None
    vals = [float(v) for v in trajectory.sigma_values]
    span = abs(vals[-1] - vals[0])
    denom = max(float(sigma_threshold), 1e-12)
    return _clip_unit(span / denom)


def build_criticality_state(
    *,
    sigma_t: float,
    sigma_threshold: float,
    singular_flag: bool,
    case_id: str | None = None,
    diagnostics: SingularDetectionDiagnostics | None = None,
    threshold_hit_time: float | None = None,
    transition_signal: TransitionSignal | None = None,
    state_trajectory: StateTrajectory | None = None,
    near_ratio: float = 0.85,
    watch_ratio: float = 0.45,
) -> CriticalityState:
    """Summarize criticality from existing detector outputs and thresholds (does not call detect())."""
    evidence: list[str] = []
    crossed: list[str] = []

    if sigma_threshold <= 0 or not math.isfinite(sigma_t) or not math.isfinite(sigma_threshold):
        return CriticalityState(
            case_id=case_id,
            status="unknown",
            nearest_threshold=None,
            distance_to_threshold=None,
            crossed_conditions=[],
            transition_candidate=False,
            level_risk=None,
            transition_risk=None,
            evidence=["invalid sigma_t or non-positive sigma_threshold"],
            interpretation="Inputs were insufficient for a bounded criticality view.",
        )

    if diagnostics is not None:
        if diagnostics.scalar_threshold_hit:
            crossed.append("scalar_threshold")
        if diagnostics.joint_hitting:
            crossed.append("joint_hitting")
        if diagnostics.distributional_trigger:
            crossed.append("distributional_trigger")
        evidence.append("singular_detection_diagnostics_attached")
    if singular_flag and not crossed:
        crossed.append("singular_detector_flag")
        if diagnostics is None:
            evidence.append("singular_flag_true_without_detailed_diagnostics")

    # level_risk: normalized scalar pressure (sigma_t is a weighted composite, not a probability).
    level_risk = _clip_unit(float(sigma_t) / float(sigma_threshold))

    distance = max(0.0, float(sigma_threshold) - float(sigma_t))
    nearest = "sigma_composite"

    tr_signal = _transition_risk_from_signal(transition_signal)
    tr_traj = _transition_risk_from_trajectory(state_trajectory, sigma_threshold)
    if tr_signal is not None and tr_traj is not None:
        transition_risk = max(tr_signal, tr_traj)
        evidence.append("transition_risk_from_signal_and_trajectory")
    elif tr_signal is not None:
        transition_risk = tr_signal
        evidence.append("transition_risk_from_transition_signal")
    elif tr_traj is not None:
        transition_risk = tr_traj
        evidence.append("transition_risk_from_state_trajectory")
    else:
        transition_risk = None
        evidence.append("no_transition_signal_or_trajectory_transition_risk_unavailable")

    if threshold_hit_time is not None:
        evidence.append(f"ode_threshold_hit_time={threshold_hit_time}")

    transition_candidate = (transition_risk is not None and transition_risk >= 0.25) or (
        threshold_hit_time is not None
    )

    if crossed:
        status = "crossed"
        interpretation = (
            "Threshold or joint conditions recorded by the existing detector view are active; "
            "sigma_t summarizes scalar composite pressure, not a probability."
        )
    elif float(sigma_t) >= near_ratio * float(sigma_threshold):
        status = "near_threshold"
        interpretation = (
            "Scalar composite pressure is close to the configured threshold; monitor for escalation."
        )
    elif float(sigma_t) >= watch_ratio * float(sigma_threshold):
        status = "watch"
        interpretation = "Pressure is elevated relative to a quiet baseline but below near-threshold band."
    else:
        status = "safe"
        interpretation = "Pressure is far from the configured scalar threshold under this diagnostic normalization."

    if transition_risk is None:
        interpretation += " No trajectory-based transition pressure was provided; transition_risk is omitted."

    return CriticalityState(
        case_id=case_id,
        status=status,
        nearest_threshold=nearest,
        distance_to_threshold=distance,
        crossed_conditions=crossed,
        transition_candidate=transition_candidate,
        level_risk=level_risk,
        transition_risk=transition_risk,
        evidence=evidence,
        interpretation=interpretation,
    )
