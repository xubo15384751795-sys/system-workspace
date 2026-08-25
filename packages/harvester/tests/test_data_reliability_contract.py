"""Regression tests for the data reliability convergence contract."""
from __future__ import annotations

import pandas as pd
import pytest

from harvester.core.availability import (
    AvailabilityContractError,
    build_availability,
    select_latest_vintage_as_of,
)
from harvester.core.source_drift import compare_normalized_frames, compare_source_signatures


def test_retrieval_is_not_publication_availability() -> None:
    availability = build_availability(
        state="UNKNOWN",
        observation_date="2026-08-18",
        source_vintage_at="2026-08-19",
        retrieved_at="2026-08-19T01:00:00Z",
        calendar_status="UNCONFIGURED",
    )

    assert availability["available_at"] is None
    assert availability["decision_usable"] is False
    assert availability["state"] == "UNKNOWN"


def test_configured_availability_requires_causal_ordering() -> None:
    availability = build_availability(
        state="AVAILABLE",
        observation_date="2026-08-18",
        source_vintage_at="2026-08-19",
        published_at="2026-08-19T01:00:00Z",
        available_at="2026-08-19T01:01:00Z",
        retrieved_at="2026-08-19T01:02:00Z",
        calendar_status="CONFIGURED",
        release_timezone="UTC",
        release_cutoff_local="01:00",
    )

    assert availability["decision_usable"] is True

    with pytest.raises(AvailabilityContractError, match="retrieved_at cannot precede"):
        build_availability(
            state="AVAILABLE",
            observation_date="2026-08-18",
            source_vintage_at="2026-08-19",
            available_at="2026-08-19T01:02:00Z",
            retrieved_at="2026-08-19T01:01:00Z",
            calendar_status="CONFIGURED",
            decision_usable=True,
        )


def test_as_of_selection_does_not_leak_a_future_revision() -> None:
    def row(vintage: str, value: float) -> dict:
        available_at = f"{vintage}T01:00:00Z"
        return {
            "series_id": "CISS",
            "observation_date": "2026-08-18",
            "source_vintage_at": vintage,
            "value": value,
            "availability": build_availability(
                state="AVAILABLE",
                observation_date="2026-08-18",
                source_vintage_at=vintage,
                published_at=f"{vintage}T00:30:00Z",
                available_at=available_at,
                retrieved_at=f"{vintage}T02:00:00Z",
                calendar_status="CONFIGURED",
            ),
        }

    revisions = [row("2026-08-19", 100.0), row("2026-08-20", 110.0)]

    before_revision = select_latest_vintage_as_of(
        revisions,
        as_of="2026-08-19T12:00:00Z",
    )
    after_revision = select_latest_vintage_as_of(
        revisions,
        as_of="2026-08-21T00:00:00Z",
    )

    assert [item["value"] for item in before_revision] == [100.0]
    assert [item["value"] for item in after_revision] == [110.0]


def test_as_of_selection_never_uses_retrieval_as_availability() -> None:
    record = {
        "series_id": "CISS",
        "observation_date": "2026-08-18",
        "source_vintage_at": "2026-08-19",
        "value": 100.0,
        "availability": {
            "state": "UNKNOWN",
            "observation_date": "2026-08-18",
            "source_vintage_at": "2026-08-19",
            "published_at": None,
            "available_at": None,
            "retrieved_at": "2026-08-19T01:00:00Z",
            "calendar_status": "UNCONFIGURED",
            "release_timezone": None,
            "release_cutoff_local": None,
            "decision_usable": False,
        },
    }

    assert select_latest_vintage_as_of([record], as_of="2026-08-20") == []


def test_as_of_selection_fails_closed_on_missing_key() -> None:
    record = {
        "source_vintage_at": "2026-08-19",
        "availability": build_availability(
            state="AVAILABLE",
            observation_date="2026-08-18",
            source_vintage_at="2026-08-19",
            available_at="2026-08-19T01:00:00Z",
            retrieved_at="2026-08-19T02:00:00Z",
            calendar_status="CONFIGURED",
        ),
    }

    with pytest.raises(AvailabilityContractError, match="PIT key fields"):
        select_latest_vintage_as_of([record], as_of="2026-08-20")


def test_as_of_selection_fails_closed_on_duplicate_visible_vintage() -> None:
    availability = build_availability(
        state="AVAILABLE",
        observation_date="2026-08-18",
        source_vintage_at="2026-08-19",
        available_at="2026-08-19T01:00:00Z",
        retrieved_at="2026-08-19T02:00:00Z",
        calendar_status="CONFIGURED",
    )
    records = [
        {
            "series_id": "CISS",
            "observation_date": "2026-08-18",
            "source_vintage_at": "2026-08-19",
            "value": 100.0,
            "availability": availability,
        },
        {
            "series_id": "CISS",
            "observation_date": "2026-08-18",
            "source_vintage_at": "2026-08-19",
            "value": 101.0,
            "availability": availability,
        },
    ]

    with pytest.raises(AvailabilityContractError, match="duplicate visible vintage"):
        select_latest_vintage_as_of(records, as_of="2026-08-20")


def test_source_signature_change_is_visible() -> None:
    before = {"SPY": {"provider": "tiingo", "normalization_profile": "etf_ohlcv.adjusted.v1", "adjusted": True, "timestamp_basis": "trading_date"}}
    after = {"SPY": {"provider": "yfinance", "normalization_profile": "etf_ohlcv.adjusted.v1", "adjusted": True, "timestamp_basis": "trading_date"}}

    result = compare_source_signatures(before, after)

    assert result["status"] == "SOURCE_DRIFT"
    assert result["changed_series"]["SPY"]["provider"]["previous"] == "tiingo"


def test_normalized_provider_parity_rejects_duplicate_keys() -> None:
    left = pd.DataFrame({"date": ["2026-08-18", "2026-08-18"], "close": [100.0, 101.0]})
    right = pd.DataFrame({"date": ["2026-08-18"], "close": [101.0]})

    result = compare_normalized_frames(left, right, value_columns=("close",))

    assert result["status"] == "SCHEMA_CHANGED"
    assert result["reason"] == "non_unique_comparison_key"


def test_normalized_provider_parity_flags_value_drift() -> None:
    left = pd.DataFrame({"date": ["2026-08-18"], "close": [100.0]})
    right = pd.DataFrame({"date": ["2026-08-18"], "close": [101.0]})

    result = compare_normalized_frames(left, right, value_columns=("close",))

    assert result["status"] == "SOURCE_DRIFT"
    assert result["mismatches"]["close"] == 1
