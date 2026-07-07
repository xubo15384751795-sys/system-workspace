from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class FeatureLayer(StrEnum):
    PAPER = "paper_aligned"
    ENGINEERING = "engineering_required"
    EXPLORATORY = "exploratory"


@dataclass(frozen=True)
class FeatureTag:
    key: str
    label: str
    layer: FeatureLayer
    rationale: str


FEATURE_TAGS: tuple[FeatureTag, ...] = (
    FeatureTag("proxy_aggregation", "M/D/K/X proxy aggregation", FeatureLayer.PAPER, "Operationalizes the paper's structural channels."),
    FeatureTag("sigma_t", "Sigma_t joint stress", FeatureLayer.PAPER, "Main joint structural stress readout."),
    FeatureTag("singular_detector", "Singular detector", FeatureLayer.PAPER, "Implements joint singular-candidate conditions."),
    FeatureTag("primitive_state", "Primitive state to derived channel mapping", FeatureLayer.PAPER, "Connects primitive paper variables to M/D/K/X."),
    FeatureTag("ode_evolution", "ODE evolution", FeatureLayer.PAPER, "Local state evolution and structural singular-time estimate."),
    FeatureTag("shadow_mass", "Shadow mass aggregate", FeatureLayer.PAPER, "Aggregate and bucketed hidden pressure state."),
    FeatureTag("operator_commutator", "Operator algebra commutator", FeatureLayer.PAPER, "Non-commutative event sequence diagnostic."),
    FeatureTag("operator_lie_bracket", "Lie bracket proxy", FeatureLayer.PAPER, "Visual proxy for ordered event-response vector fields."),
    FeatureTag("mean_field_gap", "Mean-field gap", FeatureLayer.PAPER, "Gap against the configured benchmark shadow-mass approximation."),
    FeatureTag("data_quality_manifest", "Data quality manifest", FeatureLayer.ENGINEERING, "Required to prevent mock/fallback evidence from becoming a research claim."),
    FeatureTag("provenance_tracking", "Provenance tracking", FeatureLayer.ENGINEERING, "Implementation audit trail, not a paper result."),
    FeatureTag("cache_management", "Cache management", FeatureLayer.ENGINEERING, "Runtime performance and reproducibility infrastructure."),
    FeatureTag("threshold_calibration_mode", "Threshold calibration mode", FeatureLayer.ENGINEERING, "Protocol metadata for how thresholds were fixed."),
    FeatureTag("evidence_escalation", "Evidence escalation", FeatureLayer.ENGINEERING, "Safety gate for insufficient evidence quality."),
    FeatureTag("ml_anomaly", "ML anomaly detection", FeatureLayer.EXPLORATORY, "Auxiliary model beyond the current paper claim."),
    FeatureTag("ml_narrative_drift", "ML narrative drift", FeatureLayer.EXPLORATORY, "Text/narrative signal outside the main structural proof path."),
    FeatureTag("ml_reflexivity", "ML reflexivity tracker", FeatureLayer.EXPLORATORY, "Experimental intervention-outcome signal."),
    FeatureTag("graph_coupling", "Graph coupling analysis", FeatureLayer.EXPLORATORY, "Exploratory coupling map over channel history."),
    FeatureTag("coupling_codes", "Coupling codes and bands", FeatureLayer.EXPLORATORY, "Interpretive graph labels outside paper main flow."),
    FeatureTag("belief_breach_probability", "Belief-state breach probability", FeatureLayer.EXPLORATORY, "Distributional extension until a paper mapping is frozen."),
    FeatureTag("path_rank_witness", "Finite path-rank witness", FeatureLayer.EXPLORATORY, "Finite realized-sequence proxy, not the full positive-measure condition."),
)


def tags_for_layer(layer: FeatureLayer | str) -> tuple[FeatureTag, ...]:
    normalized = FeatureLayer(layer)
    return tuple(tag for tag in FEATURE_TAGS if tag.layer == normalized)


def feature_tag(key: str) -> FeatureTag | None:
    return next((tag for tag in FEATURE_TAGS if tag.key == key), None)


def feature_keys_for_layer(layer: FeatureLayer | str) -> tuple[str, ...]:
    return tuple(tag.key for tag in tags_for_layer(layer))


def layer_summary(keys: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in keys:
        tag = feature_tag(key)
        out[key] = tag.layer.value if tag is not None else "unclassified"
    return out
