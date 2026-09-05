from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, cast, runtime_checkable

from src.core.models import _freeze_mapping as freeze_mapping, ProxyReading


Channel = str
CHANNELS: tuple[Channel, ...] = ("M", "D", "K", "X")


@dataclass(frozen=True)
class StructuralOperator:
    """
    A market event represented as a state-dependent transformation over M/D/K/X.

    Most crisis operators are intentionally modeled as semigroup elements:
    composable, path-sensitive, and usually non-invertible.
    """

    name: str
    family: str
    delta: Mapping[Channel, float]
    aliases: tuple[str, ...] = ()
    reversible: bool = False
    continuous: bool = False
    differentiable: bool = False
    state_dependent: bool = True
    compressive: bool = False
    shadow_transfer: bool = False
    reflexive: bool = False
    path_dependent: bool = True
    recovery: bool = False
    sensitivity: Mapping[str, float] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        canonical_delta = {channel: float(self.delta.get(channel, 0.0)) for channel in CHANNELS}
        object.__setattr__(self, "name", self.name.upper())
        object.__setattr__(self, "delta", freeze_mapping(canonical_delta))
        object.__setattr__(self, "sensitivity", freeze_mapping(self.sensitivity))


@dataclass(frozen=True)
class OperatorApplication:
    operator_name: str
    family: str
    intensity: float
    pre_state: Mapping[Channel, float]
    post_state: Mapping[Channel, float]
    delta: Mapping[Channel, float]
    event_id: str | None = None
    event_date: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pre_state", freeze_mapping(self.pre_state))
        object.__setattr__(self, "post_state", freeze_mapping(self.post_state))
        object.__setattr__(self, "delta", freeze_mapping(self.delta))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True)
class OperatorDiagnostics:
    """
    Typed summary produced by the structural operator algebra after applying
    an event sequence to M/D/K/X state space.
    """

    operator_count: int
    unmapped_event_count: int
    sequence_signature: str
    families: Mapping[str, int]
    compression_ratio: float
    raw_d_ratio: Optional[float]
    shadow_transfer: float
    curvature_amplification: float
    mismatch_amplification: float
    singular_pressure: float
    singular_distance: float
    singular_proximity: float
    non_commutativity_score: float
    path_rank_witness_count: int
    path_rank_max_output_separation: float
    path_rank_mean_output_separation: float
    irreversible_count: int
    jump_count: int
    compressive_count: int
    applications: tuple[OperatorApplication, ...]
    initial_state: Mapping[str, float]
    final_state: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "families", freeze_mapping(self.families))
        object.__setattr__(self, "initial_state", freeze_mapping(self.initial_state))
        object.__setattr__(self, "final_state", freeze_mapping(self.final_state))

    def to_dict(self) -> dict[str, Any]:
        from src.operators.operator_diagnostics import operator_application_to_dict

        return {
            "operator_count": self.operator_count,
            "unmapped_event_count": self.unmapped_event_count,
            "sequence_signature": self.sequence_signature,
            "families": dict(self.families),
            "compression_ratio": self.compression_ratio,
            "raw_d_ratio": self.raw_d_ratio,
            "shadow_transfer": self.shadow_transfer,
            "curvature_amplification": self.curvature_amplification,
            "mismatch_amplification": self.mismatch_amplification,
            "singular_pressure": self.singular_pressure,
            "singular_distance": self.singular_distance,
            "singular_proximity": self.singular_proximity,
            "non_commutativity_score": self.non_commutativity_score,
            "path_rank_witness_count": self.path_rank_witness_count,
            "path_rank_max_output_separation": self.path_rank_max_output_separation,
            "path_rank_mean_output_separation": self.path_rank_mean_output_separation,
            "irreversible_count": self.irreversible_count,
            "jump_count": self.jump_count,
            "compressive_count": self.compressive_count,
            "applications": [operator_application_to_dict(app) for app in self.applications],
            "initial_state": dict(self.initial_state),
            "final_state": dict(self.final_state),
        }


@dataclass(frozen=True)
class EventOperatorMatch:
    operator: StructuralOperator
    intensity: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


# ---------------------------------------------------------------------------
# Sequence algebra types (live here to keep the layer dependency one-way:
# operator_schema ← operator_algebra, never the reverse)
# ---------------------------------------------------------------------------

@runtime_checkable
class ProxyLikeState(Protocol):
    M: float | None
    D: float | None
    K: float | None
    X: float | None


@dataclass(frozen=True)
class StructuralStateOperand:
    """Wraps an M/D/K/X mapping as a typed, immutable operand for the algebra."""

    values: Mapping[str, float]
    label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, float]:
        return {channel: _finite_or_zero(self.values.get(channel, 0.0)) for channel in CHANNELS}

    @classmethod
    def from_proxy(cls, proxy: ProxyLikeState, label: str | None = None) -> StructuralStateOperand:
        return cls(
            values={channel: _finite_or_zero(getattr(proxy, channel, 0.0)) for channel in CHANNELS},
            label=label or getattr(proxy, "run_date", None),
        )


@dataclass(frozen=True)
class OperatorStep:
    """
    One ordered application in the structural operator algebra.

    Explicit step objects make path order first-class so non-commutativity
    and sequence history are preserved without changing the transformation math.
    """

    operator: StructuralOperator
    intensity: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperatorTraceEntry:
    step_index: int
    operator_name: str
    family: str
    intensity: float
    before: Mapping[str, float]
    after: Mapping[str, float]
    delta: Mapping[str, float]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperatorSequence:
    """An ordered, immutable sequence of OperatorSteps; applies them in order."""

    steps: tuple[OperatorStep, ...]

    def apply(
        self,
        state: ProxyLikeState | Mapping[str, float] | StructuralStateOperand,
    ) -> tuple[dict[str, float], list[OperatorTraceEntry]]:
        # Deferred to break the circular import with operator_algebra.py
        from src.operators.operator_algebra import apply_operator, clean_state  # noqa: PLC0415

        current = _coerce_state(state, clean_state)
        trace: list[OperatorTraceEntry] = []
        for idx, step in enumerate(self.steps):
            before = dict(current)
            current = apply_operator(before, step.operator, intensity=step.intensity)
            trace.append(
                OperatorTraceEntry(
                    step_index=idx,
                    operator_name=step.operator.name,
                    family=step.operator.family,
                    intensity=float(step.intensity),
                    before=before,
                    after=dict(current),
                    delta={ch: current[ch] - before[ch] for ch in CHANNELS},
                    metadata=dict(step.metadata),
                )
            )
        return current, trace

    def ordering_signature(self) -> tuple[str, ...]:
        return tuple(step.operator.name for step in self.steps)

    def then(self, step: OperatorStep) -> OperatorSequence:
        return OperatorSequence(steps=self.steps + (step,))

    @classmethod
    def from_steps(cls, steps: list[OperatorStep] | tuple[OperatorStep, ...]) -> OperatorSequence:
        return cls(steps=tuple(steps))


def _coerce_state(
    state: ProxyLikeState | Mapping[str, float] | StructuralStateOperand,
    clean_state_fn: Any,
) -> dict[str, float]:
    if isinstance(state, StructuralStateOperand):
        return state.as_mapping()
    if isinstance(state, ProxyReading):
        return StructuralStateOperand.from_proxy(state).as_mapping()
    if isinstance(state, Mapping):
        return cast(dict[str, float], clean_state_fn(state))
    return StructuralStateOperand.from_proxy(state).as_mapping()


def _finite_or_zero(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0
