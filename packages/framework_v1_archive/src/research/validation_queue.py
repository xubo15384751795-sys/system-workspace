from __future__ import annotations

from src.research.schemas import ClaimMaturityTag
from src.research.schemas import CandidateSignal, ValidationQueueItem


DEFAULT_VALIDATION_TESTS = (
    "public_proxy_coverage",
    "rolling_origin_oos",
    "public_baseline_rank",
    "proxy_ablation",
    "threshold_perturbation",
    "claim_guard_review",
)


def queue_candidate_signal(candidate: CandidateSignal) -> ValidationQueueItem:
    return ValidationQueueItem(
        candidate_name=candidate.name,
        maturity=candidate.maturity,
        target_to_test=candidate.target_to_test,
        required_public_proxies=candidate.required_proxies,
        tests=DEFAULT_VALIDATION_TESTS,
        blocking_criteria=(
            "No full-sample threshold fitting",
            "No future data in signal construction",
            "No early-warning language unless OOS and baseline criteria pass",
            "No portfolio language without portfolio validation",
        ),
        status="PENDING" if candidate.maturity in {ClaimMaturityTag.HYPOTHESIS, ClaimMaturityTag.PROXY_SUPPORTED, ClaimMaturityTag.CASE_SUPPORTED} else "REVIEWED",
    )


class ValidationQueue:
    def __init__(self) -> None:
        self._items: list[ValidationQueueItem] = []

    def add(self, candidate: CandidateSignal) -> ValidationQueueItem:
        item = queue_candidate_signal(candidate)
        self._items.append(item)
        return item

    def all(self) -> tuple[ValidationQueueItem, ...]:
        return tuple(self._items)
