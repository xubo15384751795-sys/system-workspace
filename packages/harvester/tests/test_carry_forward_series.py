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
    fixed = _carry_forward_missing_series(
        current,
        exports_root=exports,
        exclude_release_id="2026-08-10-r1",
    )
    ids = panel_identity_set(fixed)
    assert "FRED:RRPONTSYD" in ids
    assert "FRED:VIXCLS" in ids
