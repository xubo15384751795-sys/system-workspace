from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ClaimMaturityTag(str, Enum):
    HYPOTHESIS = "HYPOTHESIS"
    PROXY_SUPPORTED = "PROXY_SUPPORTED"
    CASE_SUPPORTED = "CASE_SUPPORTED"
    OOS_VALIDATED = "OOS_VALIDATED"
    PORTFOLIO_VALIDATED = "PORTFOLIO_VALIDATED"
    FORBIDDEN = "FORBIDDEN"


def freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(value, MappingProxyType):
        return value
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class ResearchHypothesis:
    name: str
    hypothesis: str
    mechanism_family: str
    required_proxies: tuple[str, ...]
    expected_horizon: str
    target_to_test: str
    failure_condition: str
    maturity: ClaimMaturityTag = ClaimMaturityTag.HYPOTHESIS
    allowed_claims: tuple[str, ...] = ("mechanism hypothesis", "candidate public-data proxy path")
    forbidden_claims: tuple[str, ...] = ("validated prediction", "portfolio instruction")
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True)
class StructuralMechanism:
    name: str
    description: str
    operator_names: tuple[str, ...]
    local_state_space: str
    maturity: ClaimMaturityTag
    proxy_requirements: tuple[str, ...]
    output_claim_boundary: str


@dataclass(frozen=True)
class FrontierVariable:
    name: str
    local_state_space: str
    channel: str
    construction: str
    rationale: str
    public_proxy_candidates: tuple[str, ...]
    maturity: ClaimMaturityTag = ClaimMaturityTag.HYPOTHESIS
    expected_horizon: str = "research"
    failure_condition: str = "No incremental explanatory or validation value over simpler public proxies."
    post_generation_constraints: tuple[str, ...] = (
        "Label as hypothesis until proxy-backed.",
        "Route to validation queue before warning language.",
        "No portfolio instruction.",
    )


@dataclass(frozen=True)
class LocalStateSpace:
    name: str
    thesis: str
    channels: Mapping[str, tuple[str, ...]]
    default_variables: tuple[str, ...]
    public_proxy_families: tuple[str, ...]
    maturity: ClaimMaturityTag = ClaimMaturityTag.HYPOTHESIS
    release_boundary: str = "Local structural map only; not a validated predictor."

    def __post_init__(self) -> None:
        object.__setattr__(self, "channels", freeze_mapping(self.channels))


@dataclass(frozen=True)
class MechanismComposition:
    name: str
    local_state_space: str
    mechanism_names: tuple[str, ...]
    operator_sequence: tuple[str, ...]
    generated_variable_names: tuple[str, ...]
    structure_path: tuple[str, ...]
    research_thesis: str
    maturity: ClaimMaturityTag = ClaimMaturityTag.HYPOTHESIS
    post_generation_constraints: tuple[str, ...] = (
        "May be used for scenario generation.",
        "Must be shown with maturity tag.",
        "Must not be shown as validated alpha.",
    )


@dataclass(frozen=True)
class CandidateSignal:
    name: str
    hypothesis: str
    required_proxies: tuple[str, ...]
    expected_horizon: str
    target_to_test: str
    failure_condition: str
    maturity: ClaimMaturityTag
    forbidden_claim: str
    research_admissible: bool = True


@dataclass(frozen=True)
class FrontierResearchBundle:
    local_state_spaces: tuple[LocalStateSpace, ...]
    variables: tuple[FrontierVariable, ...]
    mechanisms: tuple[StructuralMechanism, ...]
    compositions: tuple[MechanismComposition, ...]
    candidate_signals: tuple[CandidateSignal, ...]
    validation_queue: tuple["ValidationQueueItem", ...]
    release_constraints: tuple[str, ...] = (
        "Generation is allowed before validation.",
        "External release is blocked until claim maturity permits it.",
        "Portfolio language remains forbidden without portfolio validation.",
    )


@dataclass(frozen=True)
class ValidationQueueItem:
    candidate_name: str
    maturity: ClaimMaturityTag
    target_to_test: str
    required_public_proxies: tuple[str, ...]
    tests: tuple[str, ...]
    blocking_criteria: tuple[str, ...]
    status: str = "PENDING"


@dataclass(frozen=True)
class ScenarioPathResult:
    name: str
    maturity: ClaimMaturityTag
    operator_sequence: tuple[str, ...]
    scenario_path: tuple[str, ...]
    initial_state: Mapping[str, float]
    final_state: Mapping[str, float]
    trajectory: tuple[Mapping[str, float], ...]
    which_channel_breaks_first: str | None
    proxies_to_watch: tuple[str, ...]
    missing_data: tuple[str, ...]
    observability_classification: str
    allowed_claims: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    tradable_hypothesis_candidate: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial_state", freeze_mapping(self.initial_state))
        object.__setattr__(self, "final_state", freeze_mapping(self.final_state))
        object.__setattr__(self, "trajectory", tuple(freeze_mapping(row) for row in self.trajectory))
