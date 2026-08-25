from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.neutral_pressure_measurement import build_snapshot
from system_runtime.canonical_ids import validate_chain


def _panel() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=220, freq="B")
    series_ids = (
        "DERIVED:CP_TBILL_SPREAD",
        "DERIVED:SOFR_IORB_SPREAD",
        "FRED:NFCICREDIT",
        "FRED:NFCIRISK",
        "CBOE:MOVE",
        "DERIVED:SPX_ROLL_SPREAD",
    )
    rows = []
    for series_index, series_id in enumerate(series_ids):
        for index, date in enumerate(dates):
            rows.append({"date": date, "series_id": series_id, "value": index / 50 + series_index / 10})
    return pd.DataFrame(rows)


def test_snapshot_is_neutral_and_excludes_research_candidates(tmp_path: Path, monkeypatch) -> None:
    panel_path = tmp_path / "panel.parquet"
    history_path = tmp_path / "history.parquet"
    _panel().to_parquet(panel_path)
    monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "test-neutral-run")

    snapshot, history = build_snapshot(panel_path, history_path)

    assert snapshot["framework_id"] == "macro_pressure_measurement"
    assert snapshot["provenance"]["run_id"] == "test-neutral-run"
    assert snapshot["provenance"]["producer_step"] == "neutral_pressure_measurement"
    assert snapshot["provenance"]["claim_ceiling"] == "bounded_neutral_measurement"
    assert str(panel_path) in snapshot["provenance"]["input_fingerprints"]
    assert snapshot["legacy_compatibility"]["deformation_v1_theory_authority"] is False
    assert list(history.columns) == ["M", "D"]
    assert snapshot["advanced"]["sigma_vector"]["K"] is None
    assert snapshot["advanced"]["sigma_vector"]["X_agg"] is None
    assert snapshot["advanced"]["measurement_eligibility"]["K"]["operational_wiring"] == "denied"
    validate_chain(snapshot["canonical_chain"])
    assert snapshot["canonical_ids"]["measurement_id"].startswith("mea_")
    assert snapshot["canonical_ids"]["claim_id"].startswith("clm_")
    assert snapshot["canonical_chain"]["claim"]["provenance"]["claim_ceiling"] == "bounded_neutral_measurement"
    assert snapshot["canonical_chain"]["claim"]["provenance"]["promotion_allowed"] is False


def test_mixed_gauge_dates_use_bounded_common_business_calendar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    panel = _panel()
    next_date = panel["date"].max() + pd.offsets.BDay()
    # D receives a newer daily observation while M remains on the prior
    # business day.  The declared five-day carry window should keep both
    # gauges live at the common snapshot date.
    d_rows = pd.DataFrame(
        [
            {"date": next_date, "series_id": series_id, "value": 5.0}
            for series_id in (
                "FRED:NFCIRISK",
                "CBOE:MOVE",
                "DERIVED:SPX_ROLL_SPREAD",
            )
        ]
    )
    panel_path = tmp_path / "panel.parquet"
    history_path = tmp_path / "history.parquet"
    pd.concat([panel, d_rows], ignore_index=True).to_parquet(panel_path)
    monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "test-mixed-gauge-dates")

    snapshot, history = build_snapshot(panel_path, history_path)

    assert snapshot["status"] == "active_partial"
    assert snapshot["advanced"]["channel_coverage"]["complete"] is True
    assert history.loc[next_date, "M"] == history.loc[panel["date"].max(), "M"]
    assert pd.notna(history.loc[next_date, "D"])
