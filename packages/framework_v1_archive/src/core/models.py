from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Optional

import numpy as np

from src.core.feature_taxonomy import FeatureLayer, layer_summary

if TYPE_CHECKING:
    from src.operators.operator_schema import OperatorDiagnostics


def _freeze_mapping(value: Mapping) -> Mapping:
    if isinstance(value, MappingProxyType):
        return value
    return MappingProxyType(dict(value))


def _freeze_nested_mapping(
    value: Mapping[str, Mapping[str, float | None]],
) -> Mapping[str, Mapping[str, float | None]]:
    outer: dict[str, Mapping[str, float | None]] = {}
    for key, inner in dict(value).items():
        outer[str(key)] = _freeze_mapping(inner)
    return _freeze_mapping(outer)


def _model_to_dict(obj: Any) -> dict[str, Any]:
    """Generic serialization for frozen dataclass instances."""
    result: dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        val = getattr(obj, f.name)
        if isinstance(val, MappingProxyType):
            result[f.name] = dict(val)
        elif isinstance(val, np.ndarray):
            result[f.name] = val.tolist()
        elif isinstance(val, tuple) and val and hasattr(val[0], 'to_dict'):
            result[f.name] = [v.to_dict() for v in val]
        elif hasattr(val, 'to_dict'):
            result[f.name] = val.to_dict()
        elif isinstance(val, tuple):
            result[f.name] = list(val)
        else:
            result[f.name] = val
    return result


@dataclass(frozen=True)
class ProxyReading:
    run_date: str
    M: Optional[float]
    D: Optional[float]
    K: Optional[float]
    X: Optional[float]
    directions: Mapping[str, str]
    available: Mapping[str, bool]
    components: Mapping[str, Optional[float]]
    X_PRE: Optional[float] = None
    X_REALIZED: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "directions", _freeze_mapping(self.directions))
        object.__setattr__(self, "available", _freeze_mapping(self.available))
        object.__setattr__(self, "components", _freeze_mapping(self.components))


@dataclass(frozen=True)
class FastSignal:
    date: str
    M_zscore: Optional[float]
    D_zscore: Optional[float]
    K_zscore: Optional[float]
    X_zscore: Optional[float]
    composite: Optional[float]
    alert_level: str
    threshold_hits: tuple[str, ...]
    run_type: str = "DAILY"
    components: Mapping[str, Optional[float]] = MappingProxyType({})
    directions: Mapping[str, str] = MappingProxyType({})
    provenance: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "threshold_hits", tuple(str(item) for item in self.threshold_hits))
        object.__setattr__(self, "components", _freeze_mapping(self.components))
        object.__setattr__(self, "directions", _freeze_mapping(self.directions))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return _model_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FastSignal":
        return cls(
            date=str(payload.get("date", "")),
            run_type=str(payload.get("run_type", "DAILY")),
            M_zscore=payload.get("M_zscore"),
            D_zscore=payload.get("D_zscore"),
            K_zscore=payload.get("K_zscore"),
            X_zscore=payload.get("X_zscore"),
            composite=payload.get("composite"),
            alert_level=str(payload.get("alert_level", "CLEAR")),
            threshold_hits=tuple(str(item) for item in payload.get("threshold_hits", ())),
            components=payload.get("components", {}),
            directions=payload.get("directions", {}),
            provenance=payload.get("provenance", {}),
        )


@dataclass(frozen=True)
class CrossValidation:
    date: str
    canonical_date: str
    fast_date: str
    verdict: str
    confidence_multiplier: float
    agreement_per_channel: Mapping[str, bool]
    canonical_directions: Mapping[str, str]
    fast_directions: Mapping[str, str]
    alert_level: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "agreement_per_channel", _freeze_mapping(self.agreement_per_channel))
        object.__setattr__(self, "canonical_directions", _freeze_mapping(self.canonical_directions))
        object.__setattr__(self, "fast_directions", _freeze_mapping(self.fast_directions))

    def to_dict(self) -> dict[str, Any]:
        return _model_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CrossValidation":
        return cls(
            date=str(payload.get("date", "")),
            canonical_date=str(payload.get("canonical_date", "")),
            fast_date=str(payload.get("fast_date", "")),
            verdict=str(payload.get("verdict", "COHERENT")),
            confidence_multiplier=float(payload.get("confidence_multiplier", 0.0) or 0.0),
            agreement_per_channel=payload.get("agreement_per_channel", {}),
            canonical_directions=payload.get("canonical_directions", {}),
            fast_directions=payload.get("fast_directions", {}),
            alert_level=str(payload.get("alert_level", "CLEAR")),
        )


@dataclass(frozen=True)
class DistributionState:
    family: str
    transform: str
    mean: Optional[float]
    variance: Optional[float]
    raw_mean: Optional[float] = None
    raw_variance: Optional[float] = None
    lower_q: Optional[float] = None
    upper_q: Optional[float] = None
    support_min: Optional[float] = None
    support_max: Optional[float] = None
    confidence: float = 0.0
    effective_n: Optional[float] = None
    direct_evidence_weight: float = 0.0
    structural_evidence_weight: float = 0.0
    breach_prob: Optional[float] = None
    singular_mass: Optional[float] = None
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _model_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DistributionState":
        return cls(
            family=str(payload.get("family", "normal")),
            transform=str(payload.get("transform", "identity")),
            mean=payload.get("mean"),
            variance=payload.get("variance"),
            raw_mean=payload.get("raw_mean"),
            raw_variance=payload.get("raw_variance"),
            lower_q=payload.get("lower_q"),
            upper_q=payload.get("upper_q"),
            support_min=payload.get("support_min"),
            support_max=payload.get("support_max"),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            effective_n=payload.get("effective_n"),
            direct_evidence_weight=float(payload.get("direct_evidence_weight", 0.0) or 0.0),
            structural_evidence_weight=float(payload.get("structural_evidence_weight", 0.0) or 0.0),
            breach_prob=payload.get("breach_prob"),
            singular_mass=payload.get("singular_mass"),
            metadata=payload.get("metadata", {}),
        )


@dataclass(frozen=True)
class ChannelBeliefState:
    channel: str
    raw_point: Optional[float]
    transformed_point: Optional[float]
    distribution: DistributionState
    evidence_tags: tuple[str, ...] = ()
    last_update_source: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_tags", tuple(str(item) for item in self.evidence_tags))

    def to_dict(self) -> dict[str, Any]:
        return _model_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ChannelBeliefState":
        return cls(
            channel=str(payload.get("channel", "")),
            raw_point=payload.get("raw_point"),
            transformed_point=payload.get("transformed_point"),
            distribution=DistributionState.from_dict(payload.get("distribution", {})),
            evidence_tags=tuple(str(item) for item in payload.get("evidence_tags", ())),
            last_update_source=payload.get("last_update_source"),
        )


@dataclass(frozen=True)
class StructuralBeliefState:
    run_date: str
    channels: Mapping[str, ChannelBeliefState]
    joint_mode: str = "independent"
    covariance: Optional[Mapping[str, Mapping[str, float]]] = None
    sigma_distribution: Optional[DistributionState] = None
    escalation_metrics: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "channels", _freeze_mapping(self.channels))
        if self.covariance is not None:
            object.__setattr__(self, "covariance", _freeze_nested_mapping(self.covariance))
        object.__setattr__(self, "escalation_metrics", _freeze_mapping(self.escalation_metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_date": self.run_date,
            "channels": {name: state.to_dict() for name, state in self.channels.items()},
            "joint_mode": self.joint_mode,
            "covariance": (
                {name: dict(values) for name, values in self.covariance.items()}
                if self.covariance is not None
                else None
            ),
            "sigma_distribution": self.sigma_distribution.to_dict() if self.sigma_distribution is not None else None,
            "escalation_metrics": dict(self.escalation_metrics),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralBeliefState":
        channels = {
            str(name): ChannelBeliefState.from_dict(value)
            for name, value in dict(payload.get("channels", {})).items()
        }
        sigma_payload = payload.get("sigma_distribution")
        covariance_payload = payload.get("covariance")
        return cls(
            run_date=str(payload.get("run_date", "")),
            channels=channels,
            joint_mode=str(payload.get("joint_mode", "independent")),
            covariance=(
                {
                    str(name): {str(inner_key): float(inner_value) for inner_key, inner_value in dict(values).items()}
                    for name, values in dict(covariance_payload).items()
                }
                if isinstance(covariance_payload, Mapping)
                else None
            ),
            sigma_distribution=(
                DistributionState.from_dict(sigma_payload) if isinstance(sigma_payload, Mapping) else None
            ),
            escalation_metrics=payload.get("escalation_metrics", {}),
        )


@dataclass(frozen=True)
class StructuralPrimitiveState:
    """
    Reduced six-variable primitive layer from the paper:
    subject, anchor, liquidation feasibility, verifiability, positional power,
    and latency. M/D/K/X remain derived operational channels.
    """

    subject: float
    anchor: float
    liquidation_feasibility: float
    verifiability_density: float
    positional_power: float
    latency: float
    derived: Mapping[str, float] = MappingProxyType({})
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "derived", _freeze_mapping(self.derived))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _model_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralPrimitiveState":
        return cls(
            subject=float(payload.get("subject", 0.0) or 0.0),
            anchor=float(payload.get("anchor", 0.0) or 0.0),
            liquidation_feasibility=float(payload.get("liquidation_feasibility", 0.0) or 0.0),
            verifiability_density=float(payload.get("verifiability_density", 0.0) or 0.0),
            positional_power=float(payload.get("positional_power", 0.0) or 0.0),
            latency=float(payload.get("latency", 0.0) or 0.0),
            derived=payload.get("derived", {}),
            metadata=payload.get("metadata", {}),
        )


@dataclass(frozen=True)
class ShadowMassBucket:
    name: str
    horizon: str
    mass: float
    realization_intensity: float
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _model_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ShadowMassBucket":
        return cls(
            name=str(payload.get("name", "")),
            horizon=str(payload.get("horizon", "")),
            mass=float(payload.get("mass", 0.0) or 0.0),
            realization_intensity=float(payload.get("realization_intensity", 0.0) or 0.0),
            metadata=payload.get("metadata", {}),
        )


@dataclass(frozen=True)
class ShadowMassState:
    aggregate_mass: float
    forced_realization_pressure: float
    buckets: tuple[ShadowMassBucket, ...]
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "buckets", tuple(self.buckets))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _model_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ShadowMassState":
        return cls(
            aggregate_mass=float(payload.get("aggregate_mass", 0.0) or 0.0),
            forced_realization_pressure=float(payload.get("forced_realization_pressure", 0.0) or 0.0),
            buckets=tuple(ShadowMassBucket.from_dict(item) for item in payload.get("buckets", ())),
            metadata=payload.get("metadata", {}),
        )


@dataclass(frozen=True)
class MeanFieldGapState:
    actual_shadow_mass: float
    benchmark_shadow_mass: float
    gap: float
    normalized_gap: float
    metadata: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return _model_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MeanFieldGapState":
        return cls(
            actual_shadow_mass=float(payload.get("actual_shadow_mass", 0.0) or 0.0),
            benchmark_shadow_mass=float(payload.get("benchmark_shadow_mass", 0.0) or 0.0),
            gap=float(payload.get("gap", 0.0) or 0.0),
            normalized_gap=float(payload.get("normalized_gap", 0.0) or 0.0),
            metadata=payload.get("metadata", {}),
        )


@dataclass(frozen=True)
class StructuralDiagnosticState:
    date: str
    sigma_t: Optional[float]
    components: Mapping[str, Optional[float]]
    subcomponents: Mapping[str, Mapping[str, Optional[float]]]
    benchmarks: Mapping[str, Optional[float]]
    residual_diagnostics: Mapping[str, Optional[float]]
    morphology: Mapping[str, Any]
    rejection_flags: Mapping[str, bool]
    event_diagnostics: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", _freeze_mapping(self.components))
        object.__setattr__(self, "subcomponents", _freeze_nested_mapping(self.subcomponents))
        object.__setattr__(self, "benchmarks", _freeze_mapping(self.benchmarks))
        object.__setattr__(self, "residual_diagnostics", _freeze_mapping(self.residual_diagnostics))
        object.__setattr__(self, "morphology", _freeze_mapping(self.morphology))
        object.__setattr__(self, "rejection_flags", _freeze_mapping(self.rejection_flags))
        object.__setattr__(self, "event_diagnostics", _freeze_mapping(self.event_diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "sigma_t": self.sigma_t,
            "components": dict(self.components),
            "subcomponents": {name: dict(values) for name, values in self.subcomponents.items()},
            "benchmarks": dict(self.benchmarks),
            "residual_diagnostics": dict(self.residual_diagnostics),
            "morphology": dict(self.morphology),
            "event_diagnostics": dict(self.event_diagnostics),
            "rejection_flags": dict(self.rejection_flags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralDiagnosticState":
        return cls(
            date=str(payload.get("date", "")),
            sigma_t=payload.get("sigma_t"),
            components=payload.get("components", {}),
            subcomponents=payload.get("subcomponents", {}),
            benchmarks=payload.get("benchmarks", {}),
            residual_diagnostics=payload.get("residual_diagnostics", {}),
            morphology=payload.get("morphology", {}),
            event_diagnostics=payload.get("event_diagnostics", {}),
            rejection_flags=payload.get("rejection_flags", {}),
        )


@dataclass(frozen=True)
class StructuralState:
    run_date: str
    z_vector: Optional[np.ndarray]
    sigma_t: Optional[float]
    singular_flag: Optional[bool]
    leading_channel: Optional[str]
    pattern: Optional[str]
    anomaly_score: Optional[float]
    reflexivity_flags: Mapping[str, bool]
    provenance: Mapping[str, Any]
    operator_diagnostics: Optional[OperatorDiagnostics] = None
    belief_state: Optional[StructuralBeliefState] = None
    primitive_state: Optional[StructuralPrimitiveState] = None
    shadow_mass_state: Optional[ShadowMassState] = None
    mean_field_gap: Optional[MeanFieldGapState] = None
    diagnostic_state: Optional[StructuralDiagnosticState] = None
    structural_singular_time: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reflexivity_flags", _freeze_mapping(self.reflexivity_flags))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))


@dataclass(frozen=True)
class NarrativeReading:
    run_date: str
    ai_unicorn: str
    clo_cmbs: str
    policy: str
    drift_scores: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "drift_scores", _freeze_mapping(self.drift_scores))


@dataclass(frozen=True)
class Snapshot:
    run_date: str
    run_type: str
    proxy: ProxyReading
    state: StructuralState
    narrative: Optional[NarrativeReading]
    escalation: bool
    escalation_reason: Optional[str]

    def core(self) -> "SnapshotCore":
        op_subset = paper_operator_diagnostics(self.state.operator_diagnostics)
        evidence = {
            "provenance": dict(self.state.provenance),
            "feature_layers": layer_summary(
                [
                    "proxy_aggregation",
                    "sigma_t",
                    "singular_detector",
                    "primitive_state",
                    "ode_evolution",
                    "shadow_mass",
                    "operator_commutator",
                    "operator_lie_bracket",
                    "mean_field_gap",
                    "data_quality_manifest",
                    "provenance_tracking",
                    "evidence_escalation",
                ]
            ),
        }
        return SnapshotCore(
            run_date=self.run_date,
            run_type=self.run_type,
            proxy=self.proxy,
            sigma_t=self.state.sigma_t,
            singular_flag=self.state.singular_flag,
            leading_channel=self.state.leading_channel,
            pattern=self.state.pattern,
            z_vector=self.state.z_vector,
            primitive_state=self.state.primitive_state,
            shadow_mass_state=self.state.shadow_mass_state,
            mean_field_gap=self.state.mean_field_gap,
            diagnostic_state=self.state.diagnostic_state,
            structural_singular_time=self.state.structural_singular_time,
            operator_diagnostics=op_subset,
            evidence=evidence,
            escalation=self.escalation,
            escalation_reason=self.escalation_reason,
        )

    def extension(self) -> "SnapshotExtension":
        return SnapshotExtension(
            anomaly_score=self.state.anomaly_score,
            reflexivity_flags=dict(self.state.reflexivity_flags),
            narrative=self.narrative,
            belief_state=self.state.belief_state,
            coupling_diagnostics=dict(self.state.provenance.get("coupling_diagnostics", {}) or {}),
            operator_advanced_diagnostics=advanced_operator_diagnostics(self.state.operator_diagnostics),
            feature_layers=layer_summary(
                [
                    "ml_anomaly",
                    "ml_narrative_drift",
                    "ml_reflexivity",
                    "graph_coupling",
                    "coupling_codes",
                    "belief_breach_probability",
                    "path_rank_witness",
                ]
            ),
        )


@dataclass(frozen=True)
class SnapshotCore:
    run_date: str
    run_type: str
    proxy: ProxyReading
    sigma_t: Optional[float]
    singular_flag: Optional[bool]
    leading_channel: Optional[str]
    pattern: Optional[str]
    z_vector: Optional[np.ndarray]
    primitive_state: Optional[StructuralPrimitiveState]
    shadow_mass_state: Optional[ShadowMassState]
    mean_field_gap: Optional[MeanFieldGapState]
    diagnostic_state: Optional[StructuralDiagnosticState]
    structural_singular_time: Optional[float]
    operator_diagnostics: Mapping[str, Any]
    evidence: Mapping[str, Any]
    escalation: bool
    escalation_reason: Optional[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator_diagnostics", _freeze_mapping(self.operator_diagnostics))
        object.__setattr__(self, "evidence", _freeze_mapping(self.evidence))


@dataclass(frozen=True)
class SnapshotExtension:
    anomaly_score: Optional[float]
    reflexivity_flags: Mapping[str, bool]
    narrative: Optional[NarrativeReading]
    belief_state: Optional[StructuralBeliefState]
    coupling_diagnostics: Mapping[str, Any]
    operator_advanced_diagnostics: Mapping[str, Any]
    feature_layers: Mapping[str, str]
    layer: FeatureLayer = FeatureLayer.EXPLORATORY

    def __post_init__(self) -> None:
        object.__setattr__(self, "reflexivity_flags", _freeze_mapping(self.reflexivity_flags))
        object.__setattr__(self, "coupling_diagnostics", _freeze_mapping(self.coupling_diagnostics))
        object.__setattr__(self, "operator_advanced_diagnostics", _freeze_mapping(self.operator_advanced_diagnostics))
        object.__setattr__(self, "feature_layers", _freeze_mapping(self.feature_layers))


def paper_operator_diagnostics(op_diag: "OperatorDiagnostics | None") -> dict[str, Any]:
    if op_diag is None:
        return {}
    return {
        "operator_count": op_diag.operator_count,
        "sequence_signature": op_diag.sequence_signature,
        "families": dict(op_diag.families),
        "compression_ratio": op_diag.compression_ratio,
        "shadow_transfer": op_diag.shadow_transfer,
        "curvature_amplification": op_diag.curvature_amplification,
        "mismatch_amplification": op_diag.mismatch_amplification,
        "singular_pressure": op_diag.singular_pressure,
        "singular_distance": op_diag.singular_distance,
        "singular_proximity": op_diag.singular_proximity,
        "non_commutativity_score": op_diag.non_commutativity_score,
        "irreversible_count": op_diag.irreversible_count,
        "jump_count": op_diag.jump_count,
        "compressive_count": op_diag.compressive_count,
        "applications": [
            {
                "operator": app.operator_name,
                "family": app.family,
                "intensity": app.intensity,
                "event_id": app.event_id,
                "event_date": app.event_date,
                "delta": dict(app.delta),
            }
            for app in op_diag.applications
        ],
        "feature_layer": FeatureLayer.PAPER.value,
    }


def advanced_operator_diagnostics(op_diag: "OperatorDiagnostics | None") -> dict[str, Any]:
    if op_diag is None:
        return {}
    return {
        "path_rank_witness_count": op_diag.path_rank_witness_count,
        "path_rank_max_output_separation": op_diag.path_rank_max_output_separation,
        "path_rank_mean_output_separation": op_diag.path_rank_mean_output_separation,
        "raw_d_ratio": op_diag.raw_d_ratio,
        "unmapped_event_count": op_diag.unmapped_event_count,
        "feature_layer": FeatureLayer.EXPLORATORY.value,
    }
