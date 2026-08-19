from __future__ import annotations

from system_runtime.canonical_ids import build_observation, validate_observation


def test_canonical_observation_carries_explicit_availability_clocks() -> None:
    observation = build_observation(
        canonical_series_id="ETF:SPY:close",
        observed_at="2026-08-18",
        vintage_at="2026-08-19",
        value=600.0,
        source_id="yfinance",
        unit="USD",
        status="UNKNOWN",
        availability={
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
            "reason": "publication_calendar_or_available_at_not_evidenced",
        },
    )

    validate_observation(observation)
    assert observation["availability"]["decision_usable"] is False
    assert observation["status"] == "UNKNOWN"
