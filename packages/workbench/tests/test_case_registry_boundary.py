from __future__ import annotations

import pytest
from pydantic import ValidationError

from nlp.cases.case_registry import CaseProfile


def test_case_profile_is_historical_and_non_promotable() -> None:
    profile = CaseProfile(case_id="case_a", case_name="Case A")

    assert profile.artifact_class == "historical_case_profile"
    assert profile.claim_ceiling == "historical_reference_only"
    assert profile.promotion_allowed is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_class", "current_evidence"),
        ("claim_ceiling", "supported_current_claim"),
        ("promotion_allowed", True),
    ],
)
def test_case_profile_rejects_current_authority_flags(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        CaseProfile(case_id="case_a", case_name="Case A", **{field: value})
