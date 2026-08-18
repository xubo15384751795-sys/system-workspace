from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

import numpy as np

from src.core.models import ProxyReading


Channel = Literal["M", "D", "K", "X"]
CHANNELS: tuple[Channel, ...] = ("M", "D", "K", "X")


@dataclass(frozen=True)
class MechanismContribution:
    name: str
    family: str
    target_channel: Channel
    value: float
    driver: str
    description: str


@dataclass(frozen=True)
class MechanismTerm:
    """A literature mechanism translated into one M/D/K/X drift contribution."""

    name: str
    family: str
    target_channel: Channel
    driver: str
    coefficient: float
    description: str
    enabled: bool = True

    def to_operator(self):
        """
        Express this mechanism term as a StructuralOperator so it can enter
        the same non-commutative algebra as event operators.  Family is always
        "mechanism" so diagnostics can separate structural background from shocks.
        """
        from src.operators.operator_schema import StructuralOperator

        return StructuralOperator(
            name=f"MECHANISM_{self.name.upper()}",
            family="mechanism",
            delta={self.target_channel: self.coefficient},
            reversible=True,
            continuous=True,
            differentiable=True,
            state_dependent=True,
            compressive=self.coefficient < 0 and self.target_channel == "D",
            shadow_transfer=self.target_channel == "X",
            description=self.description,
        )

    def contribution(self, proxy: ProxyReading, context: dict[str, Any] | None = None) -> MechanismContribution:
        if not self.enabled:
            value = 0.0
        else:
            value = self.coefficient * _driver_value(self.driver, proxy, context or {})
        if not np.isfinite(value):
            value = 0.0
        return MechanismContribution(
            name=self.name,
            family=self.family,
            target_channel=self.target_channel,
            value=float(value),
            driver=self.driver,
            description=self.description,
        )


@dataclass
class MechanismRegistry:
    """Plugin layer for external theory without adding new mother-framework states."""

    terms: list[MechanismTerm] = field(default_factory=list)
    enabled_families: set[str] | None = None

    def aggregate(self, proxy: ProxyReading, context: dict[str, Any] | None = None) -> dict[Channel, float]:
        totals: dict[Channel, float] = {channel: 0.0 for channel in CHANNELS}
        for contribution in self.contributions(proxy, context):
            totals[contribution.target_channel] += contribution.value
        return totals

    def contributions(
        self, proxy: ProxyReading, context: dict[str, Any] | None = None
    ) -> list[MechanismContribution]:
        enabled = self.enabled_families
        out: list[MechanismContribution] = []
        for term in self.terms:
            if enabled is not None and term.family not in enabled:
                continue
            out.append(term.contribution(proxy, context))
        return out

    def as_operator_sequence(self) -> list:
        """
        Return all enabled mechanism terms as StructuralOperators (intensity 1.0,
        empty metadata) in the order they are registered.  Use as prefix_operators
        in apply_event_log_to_proxy so mechanisms compose in the same algebra as
        event operators rather than being applied separately inside the ODE engine.
        """
        enabled = self.enabled_families
        return [
            (term.to_operator(), 1.0, {})
            for term in self.terms
            if term.enabled and (enabled is None or term.family in enabled)
        ]

    def shifted_proxy(self, proxy: ProxyReading, context: dict[str, Any] | None = None) -> ProxyReading:
        totals = self.aggregate(proxy, context)
        values: dict[Channel, float | None] = {
            "M": _shift(proxy.M, totals["M"]),
            "D": _shift(proxy.D, totals["D"]),
            "K": _shift(proxy.K, totals["K"]),
            "X": _shift(proxy.X, totals["X"]),
        }
        components = dict(proxy.components)
        for channel, value in totals.items():
            components[f"mechanism_delta_{channel}"] = value
        return ProxyReading(
            run_date=proxy.run_date,
            M=values["M"],
            D=values["D"],
            K=values["K"],
            X=values["X"],
            directions=proxy.directions,
            available=proxy.available,
            components=components,
        )


def _shift(value: float | None, delta: float) -> float | None:
    base = 0.0 if value is None else float(value)
    shifted = base + float(delta)
    return shifted if np.isfinite(shifted) else base


def _driver_value(driver: str, proxy: ProxyReading, context: dict[str, Any]) -> float:
    key = driver.strip()
    upper = key.upper()
    if upper in CHANNELS:
        return _proxy_value(proxy, upper) or 0.0
    if upper == "D_CONTRACTION":
        return max(0.0, -(_proxy_value(proxy, "D") or 0.0))
    if upper == "M_STRESS":
        return max(0.0, _proxy_value(proxy, "M") or 0.0)
    if upper == "K_STRESS":
        return max(0.0, _proxy_value(proxy, "K") or 0.0)
    if upper == "X_STRESS":
        return max(0.0, _proxy_value(proxy, "X") or 0.0)
    if key in proxy.components and proxy.components[key] is not None:
        return float(proxy.components[key] or 0.0)
    if key in context:
        return _safe_float(context[key])
    if upper.lower() in context:
        return _safe_float(context[upper.lower()])
    return 0.0


def _proxy_value(proxy: ProxyReading, channel: str) -> float | None:
    if channel == "M":
        return cast(float | None, proxy.M)
    if channel == "D":
        return cast(float | None, proxy.D)
    if channel == "K":
        return cast(float | None, proxy.K)
    if channel == "X":
        return cast(float | None, proxy.X)
    return None


def _safe_float(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        return 0.0
    return out if np.isfinite(out) else 0.0
