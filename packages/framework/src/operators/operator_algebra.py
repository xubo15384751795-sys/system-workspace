from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, Mapping

import numpy as np

from src.core.models import ProxyReading
from src.operators.operator_schema import CHANNELS, OperatorApplication, StructuralOperator


EPS = 1e-9


def state_from_proxy(proxy: ProxyReading) -> dict[str, float]:
    return {
        "M": _finite_or_zero(proxy.M),
        "D": _finite_or_zero(proxy.D),
        "K": _finite_or_zero(proxy.K),
        "X": _finite_or_zero(proxy.X),
    }


def proxy_from_state(proxy: ProxyReading, state: Mapping[str, float]) -> ProxyReading:
    clean = clean_state(state)
    pre = state_from_proxy(proxy)
    return ProxyReading(
        run_date=proxy.run_date,
        M=clean["M"],
        D=clean["D"],
        K=clean["K"],
        X=clean["X"],
        directions=_directions_after_operator(proxy.directions, pre, clean),
        available=proxy.available,
        components=proxy.components,
    )


def clean_state(state: Mapping[str, Any]) -> dict[str, float]:
    return {channel: _finite_or_zero(state.get(channel, 0.0)) for channel in CHANNELS}


def apply_operator(
    state: Mapping[str, float],
    operator: StructuralOperator,
    intensity: float = 1.0,
) -> dict[str, float]:
    base = clean_state(state)
    factor = _state_multiplier(operator, base, intensity)
    out = dict(base)
    for channel in CHANNELS:
        out[channel] = _finite_or_zero(base[channel] + float(operator.delta.get(channel, 0.0)) * factor)
    return out


def apply_operator_sequence(
    state: Mapping[str, float],
    matches: Sequence[tuple[StructuralOperator, float, Mapping[str, Any]]],
) -> tuple[dict[str, float], list[OperatorApplication]]:
    current = clean_state(state)
    applications: list[OperatorApplication] = []
    for operator, intensity, metadata in matches:
        before = dict(current)
        current = apply_operator(current, operator, intensity=intensity)
        delta = {channel: current[channel] - before[channel] for channel in CHANNELS}
        applications.append(
            OperatorApplication(
                operator_name=operator.name,
                family=operator.family,
                intensity=float(intensity),
                pre_state=before,
                post_state=current,
                delta=delta,
                event_id=_string_or_none(metadata.get("event_id")),
                event_date=_string_or_none(metadata.get("event_date")),
                metadata=metadata,
            )
        )
    return current, applications


def compose(
    operators: Iterable[StructuralOperator],
    intensities: Iterable[float] | None = None,
) -> Callable[[Mapping[str, float]], dict[str, float]]:
    op_list = list(operators)
    intensity_list = list(intensities) if intensities is not None else [1.0] * len(op_list)

    def composed(state: Mapping[str, float]) -> dict[str, float]:
        current = clean_state(state)
        for operator, intensity in zip(op_list, intensity_list):
            current = apply_operator(current, operator, intensity=float(intensity))
        return current

    return composed


def non_commutativity_score(
    operator_a: StructuralOperator,
    operator_b: StructuralOperator,
    state: Mapping[str, float],
    intensity_a: float = 1.0,
    intensity_b: float = 1.0,
) -> float:
    z = clean_state(state)
    z_ab = apply_operator(apply_operator(z, operator_a, intensity_a), operator_b, intensity_b)
    z_ba = apply_operator(apply_operator(z, operator_b, intensity_b), operator_a, intensity_a)
    diff = np.array([z_ab[channel] - z_ba[channel] for channel in CHANNELS], dtype=float)
    return float(np.linalg.norm(diff))


def commutator_vector(
    operator_a: StructuralOperator,
    operator_b: StructuralOperator,
    state: Mapping[str, float],
    intensity_a: float = 1.0,
    intensity_b: float = 1.0,
) -> dict[str, float]:
    """Vector-valued order effect: O_b(O_a(z)) - O_a(O_b(z))."""

    z = clean_state(state)
    z_ab = apply_operator(apply_operator(z, operator_a, intensity_a), operator_b, intensity_b)
    z_ba = apply_operator(apply_operator(z, operator_b, intensity_b), operator_a, intensity_a)
    return {channel: float(z_ab[channel] - z_ba[channel]) for channel in CHANNELS}


def lie_bracket_vector(
    operator_a: StructuralOperator,
    operator_b: StructuralOperator,
    state: Mapping[str, float],
    intensity_a: float = 1.0,
    intensity_b: float = 1.0,
) -> dict[str, float]:
    """
    Near-identity Lie-bracket approximation for state-dependent operators.

    Operators are interpreted as vector fields X(z) = O(z) - z. The bracket is
    [X, Y](z) = DY(z) X(z) - DX(z) Y(z), estimated with a central-difference
    Jacobian so the diagnostic remains available without JAX.
    """

    z = clean_state(state)
    x_vec = _operator_vector_field(operator_a, z, intensity_a)
    y_vec = _operator_vector_field(operator_b, z, intensity_b)
    jx = _operator_vector_jacobian(operator_a, z, intensity_a)
    jy = _operator_vector_jacobian(operator_b, z, intensity_b)
    bracket = jy @ x_vec - jx @ y_vec
    return {channel: float(bracket[idx]) for idx, channel in enumerate(CHANNELS)}


def lie_bracket_norm(
    operator_a: StructuralOperator,
    operator_b: StructuralOperator,
    state: Mapping[str, float],
    intensity_a: float = 1.0,
    intensity_b: float = 1.0,
) -> float:
    bracket = lie_bracket_vector(
        operator_a,
        operator_b,
        state,
        intensity_a=intensity_a,
        intensity_b=intensity_b,
    )
    return float(np.linalg.norm([bracket[channel] for channel in CHANNELS]))


def operator_commutator_diagnostics(
    operator_a: StructuralOperator,
    operator_b: StructuralOperator,
    state: Mapping[str, float],
    intensity_a: float = 1.0,
    intensity_b: float = 1.0,
) -> dict[str, Any]:
    commutator = commutator_vector(
        operator_a,
        operator_b,
        state,
        intensity_a=intensity_a,
        intensity_b=intensity_b,
    )
    bracket = lie_bracket_vector(
        operator_a,
        operator_b,
        state,
        intensity_a=intensity_a,
        intensity_b=intensity_b,
    )
    return {
        "commutator_vector": commutator,
        "commutator_norm": float(np.linalg.norm([commutator[channel] for channel in CHANNELS])),
        "lie_bracket_vector": bracket,
        "lie_bracket_norm": float(np.linalg.norm([bracket[channel] for channel in CHANNELS])),
    }


def sequence_non_commutativity_score(
    operators: Sequence[StructuralOperator],
    state: Mapping[str, float],
) -> float:
    if len(operators) < 2:
        return 0.0
    scores = [
        non_commutativity_score(operators[idx], operators[idx + 1], state)
        for idx in range(len(operators) - 1)
    ]
    return float(np.mean(scores)) if scores else 0.0


def _state_multiplier(operator: StructuralOperator, state: Mapping[str, float], intensity: float) -> float:
    clean_intensity = _finite_or_zero(intensity)
    if clean_intensity < 0:
        clean_intensity = 0.0
    if not operator.state_dependent:
        return clean_intensity

    factor = 1.0
    for driver, coefficient in operator.sensitivity.items():
        factor += float(coefficient) * _driver_value(str(driver), state)
    return clean_intensity * float(np.clip(factor, 0.0, 4.0))


def _driver_value(driver: str, state: Mapping[str, float]) -> float:
    key = driver.strip().upper()
    if key in CHANNELS:
        return max(0.0, _finite_or_zero(state.get(key, 0.0)))
    if key == "D_CONTRACTION":
        return max(0.0, -_finite_or_zero(state.get("D", 0.0)))
    if key == "D_LOW":
        dof_capacity = max(EPS, 1.0 + _finite_or_zero(state.get("D", 0.0)))
        return min(4.0, 1.0 / dof_capacity)
    if key == "SINGULAR_PRESSURE":
        return (
            max(0.0, _finite_or_zero(state.get("M", 0.0)))
            + max(0.0, -_finite_or_zero(state.get("D", 0.0)))
            + max(0.0, _finite_or_zero(state.get("K", 0.0)))
            + max(0.0, _finite_or_zero(state.get("X", 0.0)))
        )
    if key == "SHADOW_STOCK":
        return max(0.0, _finite_or_zero(state.get("X", 0.0)))
    return 0.0


def _operator_vector_field(
    operator: StructuralOperator,
    state: Mapping[str, float],
    intensity: float,
) -> np.ndarray:
    z = clean_state(state)
    out = apply_operator(z, operator, intensity=intensity)
    return np.array([out[channel] - z[channel] for channel in CHANNELS], dtype=float)


def _operator_vector_jacobian(
    operator: StructuralOperator,
    state: Mapping[str, float],
    intensity: float,
) -> np.ndarray:
    try:
        import jax  # type: ignore
        import jax.numpy as jnp  # type: ignore

        jax.config.update("jax_enable_x64", True)

        def field(values):
            mapping = {channel: values[idx] for idx, channel in enumerate(CHANNELS)}
            factor = _state_multiplier_jax(operator, mapping, intensity)
            delta = jnp.asarray([float(operator.delta.get(channel, 0.0)) for channel in CHANNELS])
            return delta * factor

        z = jnp.asarray([clean_state(state)[channel] for channel in CHANNELS], dtype=jnp.float64)
        return np.asarray(jax.jacfwd(field)(z), dtype=float)
    except Exception:
        return _operator_vector_jacobian_fd(operator, state, intensity)


def _operator_vector_jacobian_fd(
    operator: StructuralOperator,
    state: Mapping[str, float],
    intensity: float,
) -> np.ndarray:
    eps = 1e-5
    z = np.array([clean_state(state)[channel] for channel in CHANNELS], dtype=float)
    jac = np.zeros((len(CHANNELS), len(CHANNELS)), dtype=float)
    for idx in range(len(CHANNELS)):
        step = np.zeros_like(z)
        step[idx] = eps
        plus = {channel: float(z[pos] + step[pos]) for pos, channel in enumerate(CHANNELS)}
        minus = {channel: float(z[pos] - step[pos]) for pos, channel in enumerate(CHANNELS)}
        jac[:, idx] = (
            _operator_vector_field(operator, plus, intensity)
            - _operator_vector_field(operator, minus, intensity)
        ) / (2.0 * eps)
    return jac


def _state_multiplier_jax(operator: StructuralOperator, state: Mapping[str, Any], intensity: float) -> Any:
    import jax.numpy as jnp  # type: ignore

    clean_intensity = max(0.0, float(intensity))
    if not operator.state_dependent:
        return clean_intensity
    factor = 1.0
    for driver, coefficient in operator.sensitivity.items():
        factor += float(coefficient) * _driver_value_jax(str(driver), state)
    return clean_intensity * jnp.clip(factor, 0.0, 4.0)


def _driver_value_jax(driver: str, state: Mapping[str, Any]) -> Any:
    import jax.numpy as jnp  # type: ignore

    key = driver.strip().upper()
    if key in CHANNELS:
        return jnp.maximum(0.0, state.get(key, 0.0))
    if key == "D_CONTRACTION":
        return jnp.maximum(0.0, -state.get("D", 0.0))
    if key == "D_LOW":
        dof_capacity = jnp.maximum(EPS, 1.0 + state.get("D", 0.0))
        return jnp.minimum(4.0, 1.0 / dof_capacity)
    if key == "SINGULAR_PRESSURE":
        return (
            jnp.maximum(0.0, state.get("M", 0.0))
            + jnp.maximum(0.0, -state.get("D", 0.0))
            + jnp.maximum(0.0, state.get("K", 0.0))
            + jnp.maximum(0.0, state.get("X", 0.0))
        )
    if key == "SHADOW_STOCK":
        return jnp.maximum(0.0, state.get("X", 0.0))
    return 0.0


def _directions_after_operator(
    original: Mapping[str, str],
    before: Mapping[str, float],
    after: Mapping[str, float],
) -> dict[str, str]:
    directions = dict(original)
    for channel in CHANNELS:
        delta = after[channel] - before[channel]
        if abs(delta) < 1e-12:
            continue
        if channel == "D":
            directions[channel] = "WORSENING" if delta < 0 else "IMPROVING"
        else:
            directions[channel] = "WORSENING" if delta > 0 else "IMPROVING"
    return directions


def _finite_or_zero(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        return 0.0
    return out if np.isfinite(out) else 0.0


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
