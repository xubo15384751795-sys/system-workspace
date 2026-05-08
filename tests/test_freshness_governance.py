from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Workbench" / "src"))

from workbench.freshness import build_release_freshness_manifest, classify_lag


def test_daily_and_weekly_staleness_classification() -> None:
    policy = {
        "frequency_thresholds": {
            "daily": {"fresh_lag_days": 3, "acceptable_lag_days": 10},
            "weekly": {"fresh_lag_days": 10, "acceptable_lag_days": 21},
            "unknown": {"fresh_lag_days": 10, "acceptable_lag_days": 30},
        }
    }

    assert classify_lag(2, "daily", policy) == "fresh"
    assert classify_lag(8, "daily", policy) == "acceptable_lag"
    assert classify_lag(11, "daily", policy) == "stale"
    assert classify_lag(10, "weekly", policy) == "fresh"
    assert classify_lag(20, "weekly", policy) == "acceptable_lag"
    assert classify_lag(22, "weekly", policy) == "stale"


def test_current_release_marks_tedrate_retired_and_move_missing() -> None:
    manifest = build_release_freshness_manifest(ROOT / "Data" / "harvester" / "exports" / "20260426T074656Z")
    by_series = {item["series_id"]: item for item in manifest["indicators"]}

    assert by_series["TEDRATE"]["freshness_status"] == "retired_or_unavailable"
    assert by_series["TEDRATE"]["current_diagnostics_allowed"] is False
    assert "January 2022" in by_series["TEDRATE"]["retired_reason"]

    assert by_series["MOVE"]["freshness_status"] == "missing"
    assert by_series["MOVE"]["required"] is True
    assert by_series["MOVE"]["missing_reason"] == "Not present in the admitted Harvester evidence release."
    assert manifest["model_input_validity"] == "incomplete"
    assert "MOVE is required but missing" in manifest["gate_result"]["warnings"]


def test_freshness_manifest_distinguishes_date_semantics(tmp_path: Path) -> None:
    release = tmp_path / "20260501T000000Z"
    data_dir = release / "data"
    data_dir.mkdir(parents=True)
    frame = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-04-30"),
                "series_id": "VIXCLS",
                "source_id": "fred",
                "source_series_id": "VIXCLS",
                "value": 20.0,
                "unit": "index",
                "frequency": "daily",
                "vintage_date": pd.Timestamp("2026-05-01"),
                "quality_flag": "observed",
            },
            {
                "date": pd.Timestamp("2026-04-18"),
                "series_id": "NFCI",
                "source_id": "fred_chicago_fed",
                "source_series_id": "NFCI",
                "value": -0.4,
                "unit": "index",
                "frequency": "weekly",
                "vintage_date": pd.Timestamp("2026-05-01"),
                "quality_flag": "observed",
            },
        ]
    )
    frame.to_parquet(data_dir / "benchmark_panel.parquet")
    (release / "catalog.json").write_text(
        json.dumps(
            {
                "bundle_id": release.name,
                "created_at": "2026-05-01T00:00:00Z",
                "files": [{"role": "benchmark_panel", "path": "data/benchmark_panel.parquet"}],
            }
        )
    )

    manifest = build_release_freshness_manifest(release, run_generated_at="2026-05-01T01:00:00Z", run_id="test")
    assert manifest["date_semantics"]["observation_date"].startswith("Indicator observation date")
    assert manifest["evidence_created_at"] == "2026-05-01T00:00:00Z"
    assert manifest["run_generated_at"] == "2026-05-01T01:00:00Z"
    by_series = {item["series_id"]: item for item in manifest["indicators"]}
    assert by_series["VIXCLS"]["observation_date"] == "2026-04-30"
    assert by_series["VIXCLS"]["vintage_date"] == "2026-05-01"
    assert by_series["VIXCLS"]["freshness_status"] == "fresh"
    assert by_series["NFCI"]["freshness_status"] == "acceptable_lag"
