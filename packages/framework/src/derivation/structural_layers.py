from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from src.core.models import (
    MeanFieldGapState,
    ProxyReading,
    ShadowMassBucket,
    ShadowMassState,
    StructuralPrimitiveState,
)
from src.operators.operator_schema import OperatorDiagnostics


EPS = 1e-9


@dataclass(frozen=True)
class StructuralLayerBundle:
    primitive_state: StructuralPrimitiveState
    shadow_mass_state: ShadowMassState
    mean_field_gap: MeanFieldGapState


def build_structural_layers(
    proxy: ProxyReading,
    operator_diagnostics: OperatorDiagnostics | None = None,
    config: Mapping[str, Any] | None = None,
) -> StructuralLayerBundle:
    cfg = dict(config or {})
    primitive = build_primitive_state(proxy, operator_diagnostics=operator_diagnostics, config=cfg)
    shadow = build_shadow_mass_state(proxy, primitive_state=primitive, operator_diagnostics=operator_diagnostics, config=cfg)
    gap = build_mean_field_gap(proxy, shadow_mass_state=shadow, operator_diagnostics=operator_diagnostics, config=cfg)
    return StructuralLayerBundle(
        primitive_state=primitive,
        shadow_mass_state=shadow,
        mean_field_gap=gap,
    )


def build_primitive_state(
    proxy: ProxyReading,
    operator_diagnostics: OperatorDiagnostics | None = None,
    config: Mapping[str, Any] | None = None,
) -> StructuralPrimitiveState:
    cfg = dict(config or {})
    m = _finite(proxy.M)
    d = _finite(proxy.D)
    k = _finite(proxy.K)
    x_pre = _shadow_pre(proxy)
    x_realized = _shadow_realized(proxy)
    x_total = max(x_pre, x_realized)
    d_contraction = max(0.0, -d)
    op_pressure = _operator_pressure(operator_diagnostics)

    subject = _clip01(0.45 + 0.20 * m + 0.15 * x_pre + 0.10 * op_pressure)        # heuristic projection — do NOT interpret as S (Subjects) measurement
    anchor = _clip01(0.65 - 0.20 * m - 0.10 * d_contraction + 0.05 * max(0.0, d))
    liquidation = _clip01(0.60 + 0.35 * d - 0.20 * m - 0.15 * op_pressure)      # heuristic projection — do NOT interpret as L (Liquidation paths) measurement
    verifiability = _clip01(0.65 - 0.20 * m - 0.10 * x_pre - 0.10 * k)          # heuristic projection — do NOT interpret as V (Verifiability) measurement
    positional_power = _clip01(0.25 + 0.25 * x_pre + 0.20 * k + 0.10 * op_pressure)
    latency = _clip01(0.20 + 0.25 * k + 0.15 * d_contraction + 0.10 * x_total)  # heuristic projection — do NOT interpret as tau (Latency) measurement

    mismatch = abs(subject - anchor)
    dof = max(
        0.0,
        float(cfg.get("d0", 0.35))
        + float(cfg.get("d_liquidation", 0.35)) * liquidation
        + float(cfg.get("d_verifiability", 0.25)) * verifiability
        - float(cfg.get("d_power", 0.25)) * positional_power
        - float(cfg.get("d_latency", 0.20)) * latency
        - float(cfg.get("d_mismatch", 0.25)) * mismatch,
    )
    curvature = max(0.0, k + 0.25 * positional_power + 0.20 * latency + 0.10 * op_pressure)
    shadow = max(0.0, x_pre)

    return StructuralPrimitiveState(
        subject=float(subject),
        anchor=float(anchor),
        liquidation_feasibility=float(liquidation),
        verifiability_density=float(verifiability),
        positional_power=float(positional_power),
        latency=float(latency),
        derived={
            "M": float(mismatch),
            "D": float(dof),
            "K": float(curvature),
            "Xagg_proxy_floor": float(shadow),
            "X_PRE_proxy_floor": float(x_pre),
            "X_REALIZED_proxy_floor": float(x_realized),
        },
        metadata={
            "closure": "sign_restricted_reduced_form_v1",
            "source": "proxy_plus_operator_diagnostics",
            "operator_pressure": float(op_pressure),
            "x_boundary": "X_PRE drives hidden stock; X_REALIZED is forced support/release.",
            "heuristic_projections": {
                "subject": {
                    "projection_status": "HEURISTIC_NOT_MEASUREMENT",
                    "do_not_interpret_as": "S (Subjects)",
                    "note": "Reduced-form linear closure from M/X_PRE/operator_pressure. NOT an empirically calibrated subject measurement.",
                },
                "liquidation_feasibility": {
                    "projection_status": "HEURISTIC_NOT_MEASUREMENT",
                    "do_not_interpret_as": "L (Liquidation paths)",
                    "note": "Reduced-form linear closure from D/M/operator_pressure. Liquidation trees are not separately measured.",
                },
                "verifiability_density": {
                    "projection_status": "HEURISTIC_NOT_MEASUREMENT",
                    "do_not_interpret_as": "V (Verifiability density)",
                    "note": "Reduced-form linear closure from M/X_PRE/K. V-to-X claims are not empirically supported.",
                },
                "latency": {
                    "projection_status": "HEURISTIC_NOT_MEASUREMENT",
                    "do_not_interpret_as": "tau (Latency)",
                    "note": "Reduced-form linear closure from K/D_contraction/X_total. Data hygiene/lookahead enforced separately.",
                },
            },
        },
    )


def build_shadow_mass_state(
    proxy: ProxyReading,
    primitive_state: StructuralPrimitiveState,
    operator_diagnostics: OperatorDiagnostics | None = None,
    config: Mapping[str, Any] | None = None,
) -> ShadowMassState:
    cfg = dict(config or {})
    base_x = max(0.0, _shadow_pre(proxy))
    observed_realization = max(0.0, _shadow_realized(proxy))
    m = max(0.0, _finite(proxy.M))
    d_contraction = max(0.0, -_finite(proxy.D))
    k = max(0.0, _finite(proxy.K))
    op_shadow = max(0.0, float(operator_diagnostics.shadow_transfer)) if operator_diagnostics is not None else 0.0
    coupling = 1.0 + 0.25 * m + 0.35 * d_contraction + 0.25 * k + 0.20 * op_shadow
    aggregate = max(0.0, base_x * coupling)

    weights = dict(cfg.get("bucket_weights", {})) if isinstance(cfg.get("bucket_weights"), Mapping) else {}
    bucket_specs = (
        ("immediate", "0-30d", float(weights.get("immediate", 0.20)), 0.35),
        ("short", "1-3m", float(weights.get("short", 0.30)), 0.25),
        ("medium", "3-12m", float(weights.get("medium", 0.30)), 0.20),
        ("long", "12m+", float(weights.get("long", 0.20)), 0.15),
    )
    total_weight = max(EPS, sum(max(0.0, spec[2]) for spec in bucket_specs))
    buckets: list[ShadowMassBucket] = []
    forced_pressure = observed_realization
    dcrit = float(cfg.get("dcrit", 0.35))
    kcrit = float(cfg.get("kcrit", 0.65))
    rho0 = float(cfg.get("rho0", 0.05))
    rho_d = float(cfg.get("rho_d", 0.55))
    rho_k = float(cfg.get("rho_k", 0.45))
    for name, horizon, raw_weight, horizon_release in bucket_specs:
        mass = aggregate * max(0.0, raw_weight) / total_weight
        intensity = (
            rho0
            + rho_d * max(0.0, dcrit - float(primitive_state.derived.get("D", 0.0)))
            + rho_k * max(0.0, k - kcrit)
            + horizon_release
        )
        forced_pressure += mass * intensity
        buckets.append(
            ShadowMassBucket(
                name=name,
                horizon=horizon,
                mass=float(mass),
                realization_intensity=float(intensity),
                metadata={"release_horizon_weight": horizon_release},
            )
        )

    return ShadowMassState(
        aggregate_mass=float(aggregate),
        forced_realization_pressure=float(forced_pressure),
        buckets=tuple(buckets),
        metadata={
            "equation": "multi_compartment_shadow_ode_reduced_form",
            "base_x": float(base_x),
            "observed_realization": float(observed_realization),
            "coupling_multiplier": float(coupling),
            "operator_shadow_transfer": float(op_shadow),
            "x_boundary": "base_x is X_PRE; observed_realization is X_REALIZED.",
        },
    )


def build_mean_field_gap(
    proxy: ProxyReading,
    shadow_mass_state: ShadowMassState,
    operator_diagnostics: OperatorDiagnostics | None = None,
    config: Mapping[str, Any] | None = None,
) -> MeanFieldGapState:
    cfg = dict(config or {})
    base_x = max(0.0, _shadow_pre(proxy))
    representative_coupling = float(cfg.get("representative_coupling", 0.10))
    benchmark = base_x * (1.0 + representative_coupling * max(0.0, _finite(proxy.M)))
    actual = float(shadow_mass_state.aggregate_mass)
    gap = abs(actual - benchmark)
    normalized = gap / max(EPS, abs(benchmark), abs(actual), 1.0)
    return MeanFieldGapState(
        actual_shadow_mass=actual,
        benchmark_shadow_mass=float(benchmark),
        gap=float(gap),
        normalized_gap=float(normalized),
        metadata={
            "benchmark": "decoupled_representative_shadow_load_v1",
            "operator_count": int(operator_diagnostics.operator_count) if operator_diagnostics is not None else 0,
        },
    )


def _operator_pressure(operator_diagnostics: OperatorDiagnostics | None) -> float:
    if operator_diagnostics is None:
        return 0.0
    return float(
        max(0.0, operator_diagnostics.non_commutativity_score)
        + max(0.0, 1.0 - operator_diagnostics.compression_ratio)
        + max(0.0, operator_diagnostics.shadow_transfer)
    )


def _finite(value: float | None) -> float:
    if value is None:
        return 0.0
    try:
        out = float(value)
    except Exception:
        return 0.0
    return out if np.isfinite(out) else 0.0


def _shadow_pre(proxy: ProxyReading) -> float:
    value = getattr(proxy, "X_PRE", None)
    if value is None:
        value = proxy.X
    return max(0.0, _finite(value))


def _shadow_realized(proxy: ProxyReading) -> float:
    return max(0.0, _finite(getattr(proxy, "X_REALIZED", None)))


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))
