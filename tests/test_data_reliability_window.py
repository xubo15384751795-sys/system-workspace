"""Evidence-window verification must count only explicit launchd bundles."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_data_reliability_window import build_window_report


def _write_run(
    root: Path,
    day: date,
    index: int,
    *,
    origin: str = "launchd",
    status: str = "success",
    execution_status: str = "SUCCESS",
    provider_status: str = "refreshed",
    operational_state: str = "FRESH_READY",
    tag: str = "daily_summary",
) -> None:
    run_id = f"daily_pipeline_{day:%Y%m%d}_120000_{index:06x}"
    run_dir = root / "Output" / "runs" / run_id
    run_dir.mkdir(parents=True)
    outcome = {
        "execution_status": execution_status,
        "provider_status": provider_status,
        "operational_state": operational_state,
        "provider_cache_within_grace": provider_status != "reused_after_provider_failure",
    }
    manifest = {
        "run_id": run_id,
        "mode": "daily_pipeline",
        "tag": tag,
        "run_origin": origin,
        "started_at": f"{day.isoformat()}T12:00:00+00:00",
        "status": status,
        "outcome": outcome,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "steps.jsonl").write_text("", encoding="utf-8")


def test_manual_runs_do_not_satisfy_default_path_window(tmp_path: Path) -> None:
    _write_run(tmp_path, date(2026, 8, 19), 0, origin="manual")
    report = build_window_report(tmp_path)
    assert report["status"] == "PENDING"
    assert report["observed_runs"] == 0
    assert report["consecutive_days"] == 0


def test_window_reports_complete_only_after_all_requirements(tmp_path: Path) -> None:
    start = date(2026, 8, 19)
    _write_run(
        tmp_path,
        start,
        0,
        status="partial_failure",
        execution_status="FAILED",
        provider_status="reused_after_provider_failure",
        operational_state="COMPLETED_BLOCKED",
        tag="provider_failure_stale",
    )
    _write_run(
        tmp_path,
        start + timedelta(days=1),
        1,
        provider_status="partial_provider_success",
        tag="schema_drift_parity_fixture",
    )
    parity_dir = tmp_path / "Data" / "harvester" / "provider_parity"
    parity_dir.mkdir(parents=True)
    (parity_dir / "window.json").write_text(
        json.dumps({"schema_version": "system.provider_parity_report.v1"}),
        encoding="utf-8",
    )
    for index in range(2, 14):
        _write_run(tmp_path, start + timedelta(days=index), index)
    report = build_window_report(tmp_path)
    assert report["status"] == "COMPLETE"
    assert report["consecutive_days"] == 14
    assert report["observed_runs"] == 14
    assert all(report["scenarios"].values())
