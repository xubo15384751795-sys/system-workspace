from __future__ import annotations

import pandas as pd

from harvester.quality import build_quality_report


def test_quality_report_passes_basic_panel() -> None:
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "series_id": ["FRED:A", "FRED:A"],
        "value": [1.0, 2.0],
    })

    report = build_quality_report(
        "sample_panel",
        df,
        as_of_date="2026-01-02",
        required_columns=["date", "series_id", "value"],
    )

    assert report["status"] == "passed"
    assert report["row_count"] == 2
    assert not report["blockers"]


def test_quality_report_blocks_future_dates() -> None:
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-10"]),
        "series_id": ["FRED:A"],
        "value": [1.0],
    })

    report = build_quality_report(
        "sample_panel",
        df,
        as_of_date="2026-01-02",
        required_columns=["date", "series_id", "value"],
    )

    assert report["status"] == "failed"
    assert any("no_future_dates" in blocker for blocker in report["blockers"])


def test_quality_report_can_allow_empty_dataset() -> None:
    df = pd.DataFrame(columns=["date", "series_id", "value"])

    report = build_quality_report(
        "optional_panel",
        df,
        as_of_date="2026-01-02",
        required_columns=["date", "series_id", "value"],
        allow_empty=True,
    )

    assert report["status"] == "passed"
