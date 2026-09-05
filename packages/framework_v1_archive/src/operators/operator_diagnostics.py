from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np

from src.operators.operator_algebra import clean_state, non_commutativity_score, sequence_non_commutativity_score
from src.operators.operator_schema import CHANNELS, OperatorApplication, OperatorDiagnostics, StructuralOperator


EPS = 1e-9


def compression_ratio(initial: Mapping[str, float], final: Mapping[str, float]) -> float:
    """
    Capacity-style DoF compression ratio.

    The project stores D as a stress-centered proxy where negative values mean
    contraction, so this uses 1 + D as effective capacity when raw D is not
    safely positive.
    """

    z0 = clean_state(initial)
    z1 = clean_state(final)
    d0 = z0["D"]
    d1 = z1["D"]
    if d0 > EPS and d1 > EPS:
        return float(d1 / d0)
    return float(max(EPS, 1.0 + d1) / max(EPS, 1.0 + d0))


def raw_d_ratio(initial: Mapping[str, float], final: Mapping[str, float]) -> float | None:
    z0 = clean_state(initial)
    z1 = clean_state(final)
    if abs(z0["D"]) <= EPS:
        return None
    return float(z1["D"] / z0["D"])


def shadow_transfer(initial: Mapping[str, float], final: Mapping[str, float]) -> float:
    z0 = clean_state(initial)
    z1 = clean_state(final)
    return float(z1["X"] - z0["X"])


def curvature_amplification(initial: Mapping[str, float], final: Mapping[str, float]) -> float:
    z0 = clean_state(initial)
    z1 = clean_state(final)
    return float(z1["K"] - z0["K"])


def mismatch_amplification(initial: Mapping[str, float], final: Mapping[str, float]) -> float:
    z0 = clean_state(initial)
    z1 = clean_state(final)
    return float(z1["M"] - z0["M"])


def singular_pressure(state: Mapping[str, float], weights: Mapping[str, float] | None = None) -> float:
    z = clean_state(state)
    w = dict(weights or {})
    return float(
        w.get("M", 1.0) * max(0.0, z["M"])
        + w.get("D", 1.0) * max(0.0, -z["D"])
        + w.get("K", 1.0) * max(0.0, z["K"])
        + w.get("X", 1.0) * max(0.0, z["X"])
    )


def singular_distance(
    state: Mapping[str, float],
    threshold: float = 2.0,
    weights: Mapping[str, float] | None = None,
) -> float:
    return float(threshold - singular_pressure(state, weights=weights))


def singular_proximity(
    state: Mapping[str, float],
    threshold: float = 2.0,
    weights: Mapping[str, float] | None = None,
) -> float:
    denom = max(EPS, float(threshold))
    return float(singular_pressure(state, weights=weights) / denom)


def approximate_reversibility(
    operator: StructuralOperator,
    state: Mapping[str, float],
    intervention_ops: Sequence[StructuralOperator],
) -> float | None:
    if not intervention_ops:
        return None
    from src.operators.operator_algebra import apply_operator

    z0 = clean_state(state)
    z1 = apply_operator(z0, operator)
    distances = []
    for intervention in intervention_ops:
        recovered = apply_operator(z1, intervention)
        diff = np.array([recovered[channel] - z0[channel] for channel in CHANNELS], dtype=float)
        distances.append(float(np.linalg.norm(diff)))
    return min(distances) if distances else None


def operator_sequence_diagnostics(
    applications: Sequence[OperatorApplication],
    initial_state: Mapping[str, float],
    final_state: Mapping[str, float],
    operators: Sequence[StructuralOperator] | None = None,
    singular_threshold: float = 2.0,
    singular_weights: Mapping[str, float] | None = None,
    unmapped_event_count: int = 0,
) -> OperatorDiagnostics:
    families = Counter(app.family for app in applications)
    sequence = [app.operator_name for app in applications]
    path_rank = path_rank_diagnostics(operators or [], initial_state)
    return OperatorDiagnostics(
        operator_count=len(applications),
        unmapped_event_count=int(unmapped_event_count),
        sequence_signature=" -> ".join(sequence),
        families=dict(sorted(families.items())),
        compression_ratio=compression_ratio(initial_state, final_state),
        raw_d_ratio=raw_d_ratio(initial_state, final_state),
        shadow_transfer=shadow_transfer(initial_state, final_state),
        curvature_amplification=curvature_amplification(initial_state, final_state),
        mismatch_amplification=mismatch_amplification(initial_state, final_state),
        singular_pressure=singular_pressure(final_state, weights=singular_weights),
        singular_distance=singular_distance(
            final_state,
            threshold=singular_threshold,
            weights=singular_weights,
        ),
        singular_proximity=singular_proximity(
            final_state,
            threshold=singular_threshold,
            weights=singular_weights,
        ),
        non_commutativity_score=sequence_non_commutativity_score(operators or [], initial_state),
        path_rank_witness_count=path_rank["witness_count"],
        path_rank_max_output_separation=path_rank["max_output_separation"],
        path_rank_mean_output_separation=path_rank["mean_output_separation"],
        irreversible_count=sum(1 for app in applications if not _operator_is_reversible(app, operators)),
        jump_count=sum(1 for app in applications if not _operator_is_continuous(app, operators)),
        compressive_count=sum(1 for app in applications if _operator_is_compressive(app, operators)),
        applications=tuple(applications),
        initial_state={channel: float(clean_state(initial_state)[channel]) for channel in CHANNELS},
        final_state={channel: float(clean_state(final_state)[channel]) for channel in CHANNELS},
    )


def path_rank_diagnostics(
    operators: Sequence[StructuralOperator],
    state: Mapping[str, float],
    tolerance: float = 1e-9,
) -> dict[str, float | int]:
    """
    Reduced path-rank witness over adjacent operator swaps.

    The paper's path-rank condition is a positive-measure statement over
    admissible path branches. The implementation can only audit realized
    finite operator sequences, so this reports whether adjacent paths with the
    same operator multiset produce separated structural outputs.
    """

    if len(operators) < 2:
        return {
            "witness_count": 0,
            "max_output_separation": 0.0,
            "mean_output_separation": 0.0,
        }
    separations = [
        non_commutativity_score(operators[idx], operators[idx + 1], state)
        for idx in range(len(operators) - 1)
    ]
    return {
        "witness_count": int(sum(score > tolerance for score in separations)),
        "max_output_separation": float(max(separations, default=0.0)),
        "mean_output_separation": float(np.mean(separations)) if separations else 0.0,
    }


def operator_application_to_dict(application: OperatorApplication) -> dict[str, Any]:
    return {
        "operator": application.operator_name,
        "family": application.family,
        "intensity": float(application.intensity),
        "event_id": application.event_id,
        "event_date": application.event_date,
        "delta": {channel: float(application.delta[channel]) for channel in CHANNELS},
    }


def _lookup_operator(
    application: OperatorApplication,
    operators: Sequence[StructuralOperator] | None,
) -> StructuralOperator | None:
    if not operators:
        return None
    for operator in operators:
        if operator.name == application.operator_name:
            return operator
    return None


def _operator_is_reversible(
    application: OperatorApplication,
    operators: Sequence[StructuralOperator] | None,
) -> bool:
    operator = _lookup_operator(application, operators)
    return bool(operator.reversible) if operator is not None else False


def _operator_is_continuous(
    application: OperatorApplication,
    operators: Sequence[StructuralOperator] | None,
) -> bool:
    operator = _lookup_operator(application, operators)
    return bool(operator.continuous) if operator is not None else False


def _operator_is_compressive(
    application: OperatorApplication,
    operators: Sequence[StructuralOperator] | None,
) -> bool:
    operator = _lookup_operator(application, operators)
    return bool(operator.compressive) if operator is not None else application.delta.get("D", 0.0) < 0.0
