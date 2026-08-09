"""Pandera content-clock evaluator smoke tests."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from orchestration.quality.pandera_checks import evaluate_content_clock


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
