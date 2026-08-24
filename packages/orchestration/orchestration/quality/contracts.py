"""Typed result contracts for the canonical quality evaluator."""
from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


FreshnessStatus = Literal[
    "fresh",
    "stale",
    "missing",
    "unreadable",
    "schema_fail",
    "empty",
    "calendar_unavailable",
]


class FreshnessResult(TypedDict):
    schema_version: Literal["freshness_result.v1"]
    name: str
    path: str
    date_column: str
    max_trading_days_behind: int
    decision_critical: bool
    engine: Literal["pandera"]
    calendar: str
    calendar_engine: Literal["exchange_calendars"]
    status: FreshnessStatus
    lag_days: int | None
    latest_date: str | None
    errors: list[str]
    calendar_days_behind: NotRequired[int]
    result_digest: NotRequired[str]


class QualityResult(TypedDict):
    schema_version: Literal["quality_result.v1"]
    engine: Literal["pandera"]
    evaluator: Literal["orchestration.quality.content_freshness"]
    suite: str
    suite_document: str | None
    status: Literal["PASS", "FAIL"]
    evaluated_at: str
    success: bool
    critical_failures: list[FreshnessResult]
    results: list[FreshnessResult]
    calendar_engine: Literal["exchange_calendars"]


class ProviderAvailabilityResult(TypedDict):
    schema_version: Literal["provider_availability_result.v1"]
    evaluator: Literal["orchestration.quality.provider_release"]
    provider_id: str
    series_id: str
    dataset_id: str
    provider_status: str
    decision_time: str
    observation_date: str | None
    available_at: str | None
    retrieved_at: str | None
    revision: int | None
    vintage_date: str | None
    policy_rule_id: str | None
    policy_version: str | None
    observation_frequency: NotRequired[str]
    verdict: Literal["PASS", "WARN", "BLOCKED", "FAIL"]
    reason_code: str
    errors: list[str]
    status_policy: NotRequired[dict[str, str]]
    release_calendar: NotRequired[dict[str, object]]
