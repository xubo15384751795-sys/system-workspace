"""Tests for the shadow provider publication calendar."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from orchestration.quality.provider_release_calendar import (
    evaluate_provider_release_calendar,
    load_provider_release_calendar,
    resolve_provider_release_calendar,
    validate_provider_release_calendar,
)
from orchestration.quality.provider_release import evaluate_provider_availability


ROOT = Path(__file__).resolve().parents[3]


def _event(**overrides):
    event = {
        "provider_id": "h41",
        "series_id": "primary_credit",
        "dataset_id": "official_panel",
        "observation_date": "2026-08-19",  # Wednesday -> Thursday release
        "status": "refreshed",
    }
    event.update(overrides)
    return event


def test_workspace_calendar_is_verified_but_shadow_only() -> None:
    calendar = load_provider_release_calendar(ROOT)
    validate_provider_release_calendar(calendar)

    assert calendar["schema_version"] == "workbench.provider_release_calendar.v1"
    assert calendar["mode"] == "shadow"
    assert {rule["rule_id"] for rule in calendar["rules"]} >= {
        "h41.weekly_public_release",
        "cftc.tff.weekly_public_release",
        "tiingo.cross_asset_daily_panel.mon",
        "tiingo.cross_asset_daily_panel.tue",
        "tiingo.cross_asset_daily_panel.wed",
        "tiingo.cross_asset_daily_panel.thu",
        "tiingo.cross_asset_daily_panel.fri",
    }


def test_h41_thursday_release_uses_eastern_dst_and_federal_holiday_roll() -> None:
    decision_time = datetime(2026, 8, 21, 0, 0, tzinfo=UTC)
    result = evaluate_provider_release_calendar(_event(), decision_time=decision_time, root=ROOT)

    assert result["status"] == "verified"
    assert result["expected_release_at"] == "2026-08-20T20:30:00Z"
    assert result["expected_available_at"] == "2026-08-20T20:30:00Z"
    assert result["release_due"] is True
    assert result["resolution"] == "weekday_pattern"
    assert result["reason"] == "verified_schedule"

    thanksgiving = evaluate_provider_release_calendar(
        _event(observation_date="2026-11-25"),
        decision_time=datetime(2026, 11, 30, tzinfo=UTC),
        root=ROOT,
    )
    assert thanksgiving["expected_release_at"] == "2026-11-27T21:30:00Z"
    assert thanksgiving["resolution"] == "holiday_roll_forward"


def test_cftc_tff_uses_official_2026_holiday_schedule_and_alias() -> None:
    event = _event(
        provider_id="cftc",
        series_id="CFTC_TFF_LEV_SP",
        dataset_id="benchmark_panel",
        observation_date="2026-08-18",  # Tuesday -> Friday release
    )
    result = evaluate_provider_release_calendar(
        event,
        decision_time=datetime(2026, 8, 24, tzinfo=UTC),
        root=ROOT,
    )

    assert result["status"] == "verified"
    assert result["expected_release_at"] == "2026-08-21T19:30:00Z"
    assert result["resolution"] == "official_release_date"

    # The official schedule moves this Thanksgiving-week release to Monday.
    delayed = evaluate_provider_release_calendar(
        {**event, "observation_date": "2026-11-24"},
        decision_time=datetime(2026, 12, 1, tzinfo=UTC),
        root=ROOT,
    )
    assert delayed["expected_release_at"] == "2026-11-30T20:30:00Z"


def test_unconfigured_provider_does_not_receive_a_guessed_schedule() -> None:
    result = evaluate_provider_release_calendar(
        {**_event(), "provider_id": "fred"},
        decision_time=datetime(2026, 8, 21, tzinfo=UTC),
        root=ROOT,
    )
    assert result["status"] == "unconfigured"
    assert result["expected_available_at"] is None
    assert result["release_due"] is False


def test_provider_evaluator_exposes_schedule_but_still_requires_explicit_availability() -> None:
    event = _event(available_at=None, retrieved_at="2026-08-21T00:00:00Z")
    result = evaluate_provider_availability(
        event,
        decision_time=datetime(2026, 8, 21, tzinfo=UTC),
        root=ROOT,
    )

    assert result["release_calendar"]["status"] == "verified"
    assert result["release_calendar"]["release_due"] is True
    assert result["verdict"] == "BLOCKED"
    assert result["reason_code"] == "PROVIDER_RELEASE_CALENDAR_UNCONFIGURED"


def test_tiingo_daily_eod_uses_session_weekday_and_eastern_cutoff() -> None:
    event = {
        "provider_id": "tiingo",
        "series_id": "SPY",
        "dataset_id": "cross_asset_daily_panel",
        "observation_date": "2026-09-04",  # Friday
    }
    result = evaluate_provider_release_calendar(
        event,
        decision_time=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        root=ROOT,
    )

    assert result["status"] == "verified"
    assert result["rule_id"] == "tiingo.cross_asset_daily_panel.fri"
    assert result["expected_release_at"] == "2026-09-04T21:30:00Z"
    assert result["release_due"] is True
    assert result["resolution"] == "weekday_pattern"

    monday = evaluate_provider_release_calendar(
        {**event, "observation_date": "2026-08-31", "provider_id": "etf_provider_chain"},
        decision_time=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        root=ROOT,
    )
    assert monday["rule_id"] == "tiingo.cross_asset_daily_panel.mon"
    assert monday["expected_release_at"] == "2026-08-31T21:30:00Z"

    weekend = evaluate_provider_release_calendar(
        {**event, "observation_date": "2026-09-05"},
        decision_time=datetime(2026, 9, 6, tzinfo=UTC),
        root=ROOT,
    )
    assert weekend["status"] == "invalid"
    assert weekend["reason"] == "observation_weekday_mismatch"


def test_calendar_rule_resolution_prefers_specific_cftc_rule() -> None:
    rule = resolve_provider_release_calendar(
        "cftc",
        series_id="CFTC_TFF_LEV_SP",
        dataset_id="benchmark_panel",
        root=ROOT,
    )
    assert rule is not None
    assert rule["rule_id"] == "cftc.tff.weekly_public_release"
