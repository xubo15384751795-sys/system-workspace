"""Carry-forward lag is a freshness WARN, never a window BLOCK."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from verify_data_reliability_window import build_window_report

from scripts.freshness_validator import evaluate_harvester_carry_forward
from tests.test_data_reliability_window import _write_run


def _write_release(root: Path, series: list[tuple[str, str]]) -> None:
    release = root / "Data" / "harvester" / "exports" / "2026-09-04-r1"
    (release / "data").mkdir(parents=True)
    (release / "provenance").mkdir(parents=True)
    rows = []
    for series_id, day in series:
        rows.append(
            {
                "date": pd.Timestamp(day),
                "series_id": f"FRED:{series_id}",
                "source_series_id": series_id,
                "value": 1.0,
            }
        )
    pd.DataFrame(rows).to_parquet(release / "data" / "benchmark_panel.parquet")
    provenance = {
        "schema_version": "1.0",
        "dataset_id": "benchmark_panel",
        "release_id": "2026-09-04-r1",
        "provider_outcome": {
            "status": "partial_provider_success",
            "provider": "harvester.complete",
            "requested_count": len(series),
            "succeeded_count": 0,
            "failed_count": len(series),
            "failed_series": [item[0] for item in series],
            "retrieved_at": "2026-09-04T00:00:00Z",
            "fallback_reason": "carried_forward_optional_series_after_provider_failure",
        },
    }
    (release / "provenance" / "benchmark_panel.provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    (release / "catalog.json").write_text(
        json.dumps({"as_of_date": "2026-09-04"}), encoding="utf-8"
    )
    latest = root / "Data" / "harvester" / "exports" / "latest"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(release.name)


def test_more_than_two_carry_forward_series_are_stale(tmp_path: Path) -> None:
    _write_release(
        tmp_path,
        [("AAA", "2026-09-03"), ("BBB", "2026-09-03"), ("CCC", "2026-09-03")],
    )
    result = evaluate_harvester_carry_forward(
        root=tmp_path, now=datetime(2026, 9, 4, tzinfo=UTC)
    )
    assert result["count"] == 3
    assert {row["series_id"] for row in result["series"]} == {"AAA", "BBB", "CCC"}
    assert result["exceeds"] is True
    assert result["status"] == "STALE"


def test_one_series_older_than_five_trading_days_is_stale(tmp_path: Path) -> None:
    _write_release(tmp_path, [("OLD", "2026-08-20")])
    result = evaluate_harvester_carry_forward(
        root=tmp_path, now=datetime(2026, 9, 4, tzinfo=UTC)
    )
    assert result["count"] == 1
    assert result["series"][0]["trading_days_behind"] > 5
    assert result["exceeds"] is True
    assert result["status"] == "STALE"


def test_two_recent_carry_forward_series_stay_fresh(tmp_path: Path) -> None:
    _write_release(tmp_path, [("AAA", "2026-09-03"), ("BBB", "2026-09-02")])
    result = evaluate_harvester_carry_forward(
        root=tmp_path, now=datetime(2026, 9, 4, tzinfo=UTC)
    )
    assert result["count"] == 2
    assert result["max_trading_days_behind"] <= 5
    assert result["exceeds"] is False
    assert result["status"] == "FRESH"


def test_window_marks_cache_expiry_without_blocking(tmp_path: Path) -> None:
    _write_release(
        tmp_path,
        [("AAA", "2026-08-01"), ("BBB", "2026-08-01"), ("CCC", "2026-08-01")],
    )
    _write_run(tmp_path, date(2026, 8, 22), 0)
    report = build_window_report(tmp_path, deployment_date=date(2026, 8, 22), minimum_days=14)
    assert report["scenarios"]["cache_expiry_or_stale"] is True
    assert report["qualification_by_run"]["daily_pipeline_20260822_120000_000000"]["qualified"] is True
    assert report["blockers"] == []
    assert report["status"] != "BLOCKED"
