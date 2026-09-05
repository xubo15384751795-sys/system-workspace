from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.core.models import ProxyReading


@dataclass(frozen=True)
class BenchmarkScore:
    name: str
    value: float
    signal: str
    components: dict[str, float]
    description: str


def evaluate_default_benchmarks(proxy: ProxyReading) -> list[BenchmarkScore]:
    return [
        volatility_only(proxy),
        liquidity_only(proxy),
        cfsi_like(proxy),
        srisk_like(proxy),
        bis_credit_gap_like(proxy),
    ]


def volatility_only(proxy: ProxyReading) -> BenchmarkScore:
    value = _positive(proxy.K)
    return _score(
        name="volatility_only",
        value=value,
        components={"K": value},
        description="Controls whether Kproxy adds information beyond generic volatility/tail stress.",
    )


def liquidity_only(proxy: ProxyReading) -> BenchmarkScore:
    value = _positive(-(proxy.D or 0.0))
    return _score(
        name="liquidity_only",
        value=value,
        components={"D_contraction": value},
        description="Controls against a pure market/funding liquidity stress read.",
    )


def cfsi_like(proxy: ProxyReading) -> BenchmarkScore:
    components = {
        "M": _positive(proxy.M),
        "D_contraction": _positive(-(proxy.D or 0.0)),
        "K": _positive(proxy.K),
        "X": _positive(proxy.X),
    }
    value = float(np.mean(list(components.values())))
    return _score(
        name="cfsi_like",
        value=value,
        components=components,
        description="CFSI-style broad financial stress basket without structural dynamics.",
    )


def srisk_like(proxy: ProxyReading) -> BenchmarkScore:
    components = {
        "D_contraction": _positive(-(proxy.D or 0.0)),
        "X": _positive(proxy.X),
    }
    value = float(0.7 * components["D_contraction"] + 0.3 * components["X"])
    return _score(
        name="srisk_like",
        value=value,
        components=components,
        description="SRISK-style visible capital shortfall proxy approximated from D contraction and shadow load.",
    )


def bis_credit_gap_like(proxy: ProxyReading) -> BenchmarkScore:
    value = _positive(proxy.X)
    return _score(
        name="bis_credit_gap_like",
        value=value,
        components={"X": value},
        description="Credit-gap-style shadow accumulation benchmark.",
    )


def _score(name: str, value: float, components: dict[str, float], description: str) -> BenchmarkScore:
    value = value if np.isfinite(value) else 0.0
    if value >= 1.5:
        signal = "HIGH"
    elif value >= 0.5:
        signal = "ELEVATED"
    else:
        signal = "NORMAL"
    return BenchmarkScore(name=name, value=float(value), signal=signal, components=components, description=description)


def _positive(value: float | None) -> float:
    if value is None or not np.isfinite(value):
        return 0.0
    return float(max(0.0, value))
