"""Carry-forward protects proxy catalog series when a preferred provider fails."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from harvester.official import _carry_forward_missing_series, panel_identity_set


def test_carry_forward_restores_missing_fred_series(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    prev = exports / "2026-08-09-r1" / "data"
    prev.mkdir(parents=True)
    previous = pd.DataFrame(
        {
            "date": ["2026-08-01", "2026-08-01"],
            "series_id": ["FRED:RRPONTSYD", "FRED:VIXCLS"],
            "source_id": ["fred", "fred"],
            "source_series_id": ["RRPONTSYD", "VIXCLS"],
            "value": [1.0, 2.0],
            "unit": ["", ""],
            "frequency": ["", ""],
            "vintage_date": ["2026-08-09", "2026-08-09"],
            "quality_flag": [0, 0],
        }
    )
    previous.to_parquet(prev / "benchmark_panel.parquet", index=False)

    # New fetch kept VIX but dropped RRP (simulates OpenBB-first miss).
    current = previous[previous["series_id"] == "FRED:VIXCLS"].copy()
    current.attrs["provider_outcome"] = {
        "status": "partial_provider_success",
        "provider": "harvester.registry",
        "requested_count": 2,
        "succeeded_count": 1,
        "failed_count": 1,
        "failed_series": ["RRPONTSYD"],
        "retrieved_at": "2026-08-10T00:00:00Z",
    }
    fixed = _carry_forward_missing_series(
        current,
        exports_root=exports,
        exclude_release_id="2026-08-10-r1",
    )
    ids = panel_identity_set(fixed)
    assert "FRED:RRPONTSYD" in ids
    assert "FRED:VIXCLS" in ids
    outcome = fixed.attrs["provider_outcome"]
    # RRP is optional for release admission.  Carrying it forward is a
    # degraded evidence outcome, not a Harvester process failure.
    assert outcome["status"] == "partial_provider_success"
    assert outcome["failed_count"] >= 1
    assert "RRPONTSYD" in outcome["failed_series"]


def test_carry_forward_required_series_remains_fail_closed(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    prev = exports / "2026-08-09-r1" / "data"
    prev.mkdir(parents=True)
    previous = pd.DataFrame(
        {
            "date": ["2026-08-01"],
            "series_id": ["FRED:NFCI"],
            "source_id": ["fred"],
            "source_series_id": ["NFCI"],
            "value": [1.0],
            "unit": [""],
            "frequency": ["weekly"],
            "vintage_date": ["2026-08-09"],
            "quality_flag": [0],
        }
    )
    previous.to_parquet(prev / "benchmark_panel.parquet", index=False)

    current = pd.DataFrame(columns=previous.columns)
    current.attrs["provider_outcome"] = {
        "status": "partial_provider_success",
        "provider": "harvester.registry",
        "requested_count": 1,
        "succeeded_count": 0,
        "failed_count": 1,
        "failed_series": ["NFCI"],
        "retrieved_at": "2026-08-10T00:00:00Z",
    }
    fixed = _carry_forward_missing_series(
        current,
        exports_root=exports,
        exclude_release_id="2026-08-10-r1",
    )
    outcome = fixed.attrs["provider_outcome"]
    assert "FRED:NFCI" in panel_identity_set(fixed)
    assert outcome["status"] == "reused_after_provider_failure"


def test_optional_failure_does_not_inherit_required_alias_from_carried_row(
    tmp_path: Path,
) -> None:
    """A carried CBOE/MOVE alias must not make an optional outage fatal."""
    exports = tmp_path / "exports"
    prev = exports / "2026-08-09-r1" / "data"
    prev.mkdir(parents=True)
    previous = pd.DataFrame(
        {
            "date": ["2026-08-01"],
            "series_id": ["CBOE:MOVE"],
            "source_id": ["cboe_direct"],
            "source_series_id": ["VXTLT"],
            "value": [1.0],
            "unit": ["index"],
            "frequency": ["daily"],
            "vintage_date": ["2026-08-09"],
            "quality_flag": [0],
        }
    )
    previous.to_parquet(prev / "benchmark_panel.parquet", index=False)

    current = pd.DataFrame(columns=previous.columns)
    current.attrs["provider_outcome"] = {
        "status": "partial_provider_success",
        "provider": "harvester.registry",
        "requested_count": 1,
        "succeeded_count": 0,
        "failed_count": 1,
        "failed_series": ["HYG"],
        "retrieved_at": "2026-08-10T00:00:00Z",
    }
    fixed = _carry_forward_missing_series(
        current,
        exports_root=exports,
        exclude_release_id="2026-08-10-r1",
    )
    outcome = fixed.attrs["provider_outcome"]
    assert "CBOE:MOVE" in panel_identity_set(fixed)
    assert outcome["status"] == "partial_provider_success"
