"""Freshness governance contracts (hermetic).

Live Harvester release probes live in test_freshness_governance_operator.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "workbench" / "src"))

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

    manifest = build_release_freshness_manifest(
        release, run_generated_at="2026-05-01T01:00:00Z", run_id="test"
    )
    assert manifest["date_semantics"]["observation_date"].startswith("Indicator observation date")
    assert manifest["evidence_created_at"] == "2026-05-01T00:00:00Z"
    assert manifest["run_generated_at"] == "2026-05-01T01:00:00Z"
    by_series = {item["series_id"]: item for item in manifest["indicators"]}
    assert by_series["VIXCLS"]["observation_date"] == "2026-04-30"
    assert by_series["VIXCLS"]["vintage_date"] == "2026-05-01"
    assert by_series["VIXCLS"]["freshness_status"] == "fresh"
    assert by_series["NFCI"]["freshness_status"] == "acceptable_lag"


def test_evidence_release_ttl_policy_exists() -> None:
    policy_path = ROOT / "configs" / "freshness_policy.yaml"
    assert policy_path.exists()
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    assert "evidence_release" in policy, "freshness_policy.yaml missing evidence_release section"
    er = policy["evidence_release"]
    assert er["default_ttl_days"] == 3
    assert er["core_judgment_on_expired"] == "blocked"
    assert er["research_on_expired"] == "allowed_with_stale_warning"
    assert er["training_feedback_on_expired"] == "allowed_if_marked_stale"


def test_constitution_has_evidence_release_ttl() -> None:
    constitution_path = ROOT / "governance" / "system_constitution.yaml"
    constitution = yaml.safe_load(constitution_path.read_text(encoding="utf-8"))
    fr = constitution["freshness_rules"]
    assert fr["evidence_release_ttl_days"] == 3
    assert fr["core_judgment_on_expired_snapshot"] == "blocked"
    assert fr["research_use_on_expired_snapshot"] == "allowed_with_stale_warning"
    assert fr["training_feedback_on_expired_snapshot"] == "allowed_if_marked_stale"
