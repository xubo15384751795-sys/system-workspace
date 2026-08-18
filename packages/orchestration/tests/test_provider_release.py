"""Provider release calendar and causal availability contract tests."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestration.quality.provider_release import (
    evaluate_provider_availability,
    load_provider_release_policy,
    ProviderReleasePolicyError,
    validate_provider_release_policy,
)


DECISION_TIME = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]

STATUS_MATRIX = {
    "refreshed": {"diagnostic": "ALLOW", "decision": "ALLOW", "watch_zero": "NOT_REQUIRED", "feedback": "ELIGIBLE_AFTER_REVIEW", "alert": "INFO", "evaluator_verdict": "PASS"},
    "reused_same_content": {"diagnostic": "ALLOW", "decision": "CONDITIONAL", "watch_zero": "CONDITIONAL", "feedback": "REVIEW_REQUIRED", "alert": "NOTICE", "evaluator_verdict": "WARN"},
    "reused_after_provider_failure": {"diagnostic": "ALLOW", "decision": "DENY", "watch_zero": "DIAGNOSTIC_ONLY", "feedback": "DENY", "alert": "ERROR", "evaluator_verdict": "BLOCKED"},
    "partial_provider_success": {"diagnostic": "ALLOW", "decision": "CONDITIONAL", "watch_zero": "CONDITIONAL", "feedback": "REVIEW_REQUIRED", "alert": "WARNING", "evaluator_verdict": "WARN"},
    "provider_failed_no_acceptable_fallback": {"diagnostic": "FAILURE_ONLY", "decision": "DENY", "watch_zero": "DIAGNOSTIC_ONLY", "feedback": "DENY", "alert": "ERROR", "evaluator_verdict": "FAIL"},
    "no_release_expected": {"diagnostic": "ALLOW", "decision": "CONDITIONAL", "watch_zero": "CONDITIONAL", "feedback": "REVIEW_REQUIRED", "alert": "INFO", "evaluator_verdict": "PASS"},
    "environmentally_blocked": {"diagnostic": "ALLOW", "decision": "DENY", "watch_zero": "DIAGNOSTIC_ONLY", "feedback": "DENY", "alert": "WARNING", "evaluator_verdict": "WARN"},
}


def _policy(
    *,
    calendar_status: str = "configured",
    reuse_policy: str = "blocked_unless_explicit",
    release_expectation: str = "scheduled",
    provider_id: str = "fred",
    series_id: str = "NFCI",
    dataset_id: str = "official_panel",
    rule_id: str = "fixture.fred.NFCI",
):
    return {
        "schema_version": "workbench.provider_release_policy.v1",
        "status_matrix": STATUS_MATRIX,
        "rules": [
            {
                "rule_id": rule_id,
                "provider_id": provider_id,
                "series_id": series_id,
                "dataset_id": dataset_id,
                "observation_frequency": "weekly",
                "calendar_status": calendar_status,
                "release_expectation": release_expectation,
                "release_timezone": "America/New_York" if calendar_status == "configured" else None,
                "release_cutoff_local": "16:00" if calendar_status == "configured" else None,
                "nominal_publication_lag": "P1D" if calendar_status == "configured" else None,
                "business_calendar_basis": "XNYS",
                "revision_vintage_policy": "explicit_vintage",
                "deletion_correction_policy": "append_correction",
                "reuse_policy": reuse_policy,
                "rule_version": "fixture.v1",
                "owner": "test",
                "official_evidence_url": "https://example.test/provider-docs",
            }
        ],
    }


def _event(**overrides):
    event = {
        "provider_id": "fred",
        "series_id": "NFCI",
        "dataset_id": "official_panel",
        "status": "refreshed",
        "observation_date": "2026-08-11",
        "available_at": "2026-08-12T08:00:00Z",
        "retrieved_at": "2026-08-12T09:00:00Z",
        "revision": 1,
        "vintage_date": "2026-08-12",
    }
    event.update(overrides)
    return event


def test_workspace_policy_is_versioned_and_explicitly_unconfigured() -> None:
    payload = load_provider_release_policy(ROOT)
    validate_provider_release_policy(payload)
    assert payload["schema_version"] == "workbench.provider_release_policy.v1"
    assert len(payload["rules"]) == 12
    assert all(rule["calendar_status"] == "unconfigured" for rule in payload["rules"])


def test_available_at_before_decision_is_pass() -> None:
    result = evaluate_provider_availability(
        _event(), decision_time=DECISION_TIME, policy=_policy()
    )
    assert result["verdict"] == "PASS"
    assert result["reason_code"] == "PROVIDER_AVAILABLE_BEFORE_DECISION"
    assert result["status_policy"] == STATUS_MATRIX["refreshed"]


def test_available_at_after_decision_is_blocked() -> None:
    result = evaluate_provider_availability(
        _event(available_at="2026-08-12T13:00:00Z"),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )
    assert result["verdict"] == "BLOCKED"
    assert "available_after_decision" in result["errors"]


@pytest.mark.parametrize(
    ("provider_id", "series_id", "dataset_id"),
    (
        ("direct_ofr", "OFR_FSI", "benchmark_panel"),
        ("fred", "NFCI", "official_panel"),
        ("ecb", "CISS", "benchmark_panel"),
    ),
)
def test_ofr_fred_ecb_share_the_same_causal_availability_contract(
    provider_id: str, series_id: str, dataset_id: str
) -> None:
    policy = _policy(
        provider_id=provider_id,
        series_id=series_id,
        dataset_id=dataset_id,
        rule_id=f"fixture.{provider_id}.{series_id}",
    )
    event = _event(
        provider_id=provider_id,
        series_id=series_id,
        dataset_id=dataset_id,
    )

    available = evaluate_provider_availability(
        event, decision_time=DECISION_TIME, policy=policy
    )
    assert available["verdict"] == "PASS"

    late = evaluate_provider_availability(
        {**event, "available_at": "2026-08-12T13:00:00Z"},
        decision_time=DECISION_TIME,
        policy=policy,
    )
    assert late["verdict"] == "BLOCKED"
    assert "available_after_decision" in late["errors"]


def test_retrieved_at_cannot_replace_or_precede_available_at() -> None:
    result = evaluate_provider_availability(
        _event(retrieved_at="2026-08-12T07:00:00Z"),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )
    assert result["verdict"] == "BLOCKED"
    assert "retrieved_before_available" in result["errors"]


def test_missing_available_at_is_blocked() -> None:
    result = evaluate_provider_availability(
        _event(available_at=None), decision_time=DECISION_TIME, policy=_policy()
    )
    assert result["verdict"] == "BLOCKED"
    assert result["reason_code"] == "MISSING_CAUSAL_AVAILABILITY_EVIDENCE"


def test_explicit_vintage_requires_revision_and_non_lookahead_vintage() -> None:
    missing = evaluate_provider_availability(
        _event(revision=None, vintage_date=None),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )
    assert missing["verdict"] == "BLOCKED"
    assert "missing_vintage_date" in missing["errors"]
    assert "invalid_revision" in missing["errors"]

    before_observation = evaluate_provider_availability(
        _event(vintage_date="2026-08-10"),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )
    assert before_observation["verdict"] == "BLOCKED"
    assert "vintage_before_observation" in before_observation["errors"]


def test_provider_failure_and_reuse_are_not_pass() -> None:
    for status, expected in (
        ("reused_after_provider_failure", "REUSED_AFTER_PROVIDER_FAILURE"),
        (
            "provider_failed_no_acceptable_fallback",
            "PROVIDER_FAILED_NO_ACCEPTABLE_FALLBACK",
        ),
    ):
        result = evaluate_provider_availability(
            _event(status=status), decision_time=DECISION_TIME, policy=_policy()
        )
        assert result["reason_code"] == expected
        assert result["verdict"] in {"BLOCKED", "FAIL"}


def test_no_release_expected_requires_explicit_release_policy() -> None:
    result = evaluate_provider_availability(
        _event(status="no_release_expected"),
        decision_time=DECISION_TIME,
        policy=_policy(release_expectation="no_scheduled_release"),
    )
    assert result["verdict"] == "PASS"
    assert result["reason_code"] == "NO_RELEASE_EXPECTED"

    blocked = evaluate_provider_availability(
        _event(status="no_release_expected"),
        decision_time=DECISION_TIME,
        policy=_policy(release_expectation="scheduled"),
    )
    assert blocked["verdict"] == "BLOCKED"
    assert blocked["reason_code"] == "NO_RELEASE_POLICY_NOT_PROVEN"


def test_environmentally_blocked_is_diagnostic_only_and_not_decision_pass() -> None:
    result = evaluate_provider_availability(
        _event(status="environmentally_blocked", available_at=None, retrieved_at=None),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )
    assert result["verdict"] == "WARN"
    assert result["reason_code"] == "ENVIRONMENTALLY_BLOCKED"
    assert result["status_policy"]["decision"] == "DENY"
    assert result["status_policy"]["watch_zero"] == "DIAGNOSTIC_ONLY"


def test_unconfigured_calendar_blocks_even_with_timestamps() -> None:
    result = evaluate_provider_availability(
        _event(), decision_time=DECISION_TIME, policy=_policy(calendar_status="unconfigured")
    )
    assert result["verdict"] == "BLOCKED"
    assert result["reason_code"] == "PROVIDER_RELEASE_CALENDAR_UNCONFIGURED"


def test_configured_calendar_fields_must_be_executable() -> None:
    invalid_timezone = _policy()
    invalid_timezone["rules"][0]["release_timezone"] = "Mars/Phobos"
    with pytest.raises(ProviderReleasePolicyError, match="invalid release timezone"):
        validate_provider_release_policy(invalid_timezone)

    invalid_cutoff = _policy()
    invalid_cutoff["rules"][0]["release_cutoff_local"] = "25:99"
    with pytest.raises(ProviderReleasePolicyError, match="invalid release cutoff"):
        validate_provider_release_policy(invalid_cutoff)

    invalid_lag = _policy()
    invalid_lag["rules"][0]["nominal_publication_lag"] = "tomorrow"
    with pytest.raises(ProviderReleasePolicyError, match="publication lag"):
        validate_provider_release_policy(invalid_lag)

    invalid_frequency = _policy()
    invalid_frequency["rules"][0]["observation_frequency"] = "unknown"
    with pytest.raises(ProviderReleasePolicyError, match="observation_frequency"):
        validate_provider_release_policy(invalid_frequency)


def test_workspace_status_matrix_covers_every_provider_outcome() -> None:
    policy = load_provider_release_policy(ROOT)
    assert set(policy["status_matrix"]) == set(STATUS_MATRIX)
    assert all(
        set(entry) >= set(STATUS_MATRIX[status])
        for status, entry in policy["status_matrix"].items()
    )

    invalid = _policy()
    invalid["status_matrix"]["refreshed"]["decision"] = "MAYBE"
    with pytest.raises(ProviderReleasePolicyError, match="status_matrix value invalid"):
        validate_provider_release_policy(invalid)
