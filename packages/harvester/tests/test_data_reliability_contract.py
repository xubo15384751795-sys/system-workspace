"""Regression tests for the data reliability convergence contract."""
from __future__ import annotations

import pandas as pd
import pytest

from harvester.core.availability import AvailabilityContractError, build_availability
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
