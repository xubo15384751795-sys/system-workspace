from __future__ import annotations

from src.research.schemas import ClaimMaturityTag
from src.research.hypothesis_registry import ResearchHypothesisRegistry
from src.research.schemas import CandidateSignal, ResearchHypothesis


class CandidateSignalFactory:
    def __init__(self, registry: ResearchHypothesisRegistry | None = None) -> None:
        self.registry = registry or ResearchHypothesisRegistry()

    def from_hypothesis(self, hypothesis: ResearchHypothesis) -> CandidateSignal:
        return CandidateSignal(
            name=hypothesis.name,
            hypothesis=hypothesis.hypothesis,
            required_proxies=hypothesis.required_proxies,
            expected_horizon=hypothesis.expected_horizon,
            target_to_test=hypothesis.target_to_test,
            failure_condition=hypothesis.failure_condition,
            maturity=hypothesis.maturity,
            forbidden_claim=", ".join(hypothesis.forbidden_claims),
            research_admissible=hypothesis.maturity != ClaimMaturityTag.FORBIDDEN,
        )

    def build_all(self) -> tuple[CandidateSignal, ...]:
        return tuple(self.from_hypothesis(item) for item in self.registry.all())
