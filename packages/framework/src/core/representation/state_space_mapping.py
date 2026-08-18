from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, cast, runtime_checkable

import numpy as np

from src.core.models import ProxyReading


STATE_VECTOR_LABELS = ("M_obs", "M_latent", "D_obs", "D_latent", "K_mode", "X_mode")


@dataclass(frozen=True)
class StructuralStateVector:
    values: np.ndarray
    labels: tuple[str, ...] = STATE_VECTOR_LABELS

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", np.asarray(self.values, dtype=float))

    def as_array(self) -> np.ndarray:
        return cast(np.ndarray, np.asarray(self.values, dtype=float))

    def as_mapping(self) -> dict[str, float]:
        return {label: float(value) for label, value in zip(self.labels, self.values)}


@runtime_checkable
class StateSpaceMapping(Protocol):
    """
    Structural state initialization is a modeling assumption.

    This protocol exists so the M/D/K/X proxy layer can be mapped into an
    initial latent state space explicitly, inspected, and versioned rather than
    remaining a hidden numerical convenience inside the ODE engine.
    """

    mapping_name: str
    mapping_version: str
    state_labels: tuple[str, ...]

    def map_proxy(self, proxy: ProxyReading) -> StructuralStateVector:
        ...

    def describe(self) -> dict[str, object]:
        ...


@dataclass(frozen=True)
class DefaultStateSpaceMapping:
    """
    Default structural embedding from proxy observables into ODE state space.

    The specific placement of M/D/K/X into the six-dimensional initial vector is
    a model choice about structural interpretation, not merely a numerical
    helper. Keeping it explicit makes the assumption inspectable and versionable.
    """

    mapping_name: str = "default_structural_state_space"
    mapping_version: str = "v1"
    state_labels: tuple[str, ...] = field(default=STATE_VECTOR_LABELS)

    def map_proxy(self, proxy: ProxyReading) -> StructuralStateVector:
        m = _finite_or_zero(proxy.M)
        d = _finite_or_zero(proxy.D, default=0.5)
        k = _finite_or_zero(proxy.K)
        x = _finite_or_zero(proxy.X)
        return StructuralStateVector(
            values=np.array([m / 2.0, m / 2.0, d, (d + m) / 2.0, k, x], dtype=float),
            labels=self.state_labels,
        )

    def describe(self) -> dict[str, object]:
        return {
            "mapping_name": self.mapping_name,
            "mapping_version": self.mapping_version,
            "state_labels": self.state_labels,
        }


def _finite_or_zero(value: float | None, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    out = float(value)
    if not np.isfinite(out):
        return float(default)
    return out
