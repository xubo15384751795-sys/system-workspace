"""Pandera content-clock evaluator smoke tests."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from orchestration.quality.pandera_checks import evaluate_content_clock
from orchestration.quality.calendar_engine import session_bounds, sessions_behind


def test_evaluate_content_clock_fresh(tmp_path: Path):
    panel = tmp_path / "panel.parquet"
    pd.DataFrame({"date": ["2026-08-08", "2026-08-09"], "v": [1, 2]}).to_parquet(panel)
    result = evaluate_content_clock(
        "demo",
        {
            "path": str(panel),
            "date_column": "date",
            "max_trading_days_behind": 5,
            "decision_critical": True,
        },
        root=tmp_path,
        as_of=date(2026, 8, 9),
    )
    assert result["status"] == "fresh"
    assert result["engine"] == "pandera"
    assert result["calendar"] == "XNYS"
    assert result["calendar_engine"] == "exchange_calendars"


def test_evaluate_content_clock_missing(tmp_path: Path):
    result = evaluate_content_clock(
        "missing",
        {
            "path": "nope.parquet",
            "date_column": "date",
            "max_trading_days_behind": 3,
            "decision_critical": True,
        },
        root=tmp_path,
        as_of=date(2026, 8, 9),
    )
    assert result["status"] == "missing"


def test_calendar_engine_excludes_nyse_holiday(tmp_path: Path):
    # 2026-07-03 is the observed Independence Day holiday; only 2026-07-06
    # is a session after the 2026-07-02 observation.
    assert sessions_behind(date(2026, 7, 2), date(2026, 7, 6)) == 1


def test_calendar_engine_exposes_nyse_early_close_and_utc_boundaries() -> None:
    from zoneinfo import ZoneInfo

    _, normal_close = session_bounds(date(2026, 11, 25))
    _, early_close = session_bounds(date(2026, 11, 27))

    assert normal_close.hour == 21
    assert early_close.hour == 18
    assert early_close.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M") == "13:00"
    assert early_close.astimezone(ZoneInfo("Asia/Singapore")).date() == date(2026, 11, 28)


def test_calendar_engine_rejects_holiday_session_bounds() -> None:
    import pytest

    with pytest.raises(RuntimeError, match="not an exchange session"):
        session_bounds(date(2026, 7, 3))
