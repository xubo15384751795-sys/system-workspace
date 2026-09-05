"""Evidence-window verification must count only explicit launchd bundles."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_data_reliability_window import DEFAULT_DEPLOYMENT_DATE, build_window_report


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
    publish_status: str = "COMMITTED",
    failed_steps: list[str] | None = None,
    blocked_steps: list[str] | None = None,
    fallback_used: bool | None = None,
    series_attempts: dict[str, list[dict[str, object]]] | None = None,
    cache_within_grace: bool | None = None,
    availability_state: str | None = None,
) -> None:
    run_id = f"daily_pipeline_{day:%Y%m%d}_120000_{index:06x}"
    run_dir = root / "Output" / "runs" / run_id
    run_dir.mkdir(parents=True)
    outcome = {
        "execution_status": execution_status,
        "failed_steps": failed_steps or [],
        "blocked_steps": blocked_steps or [],
        "provider_status": provider_status,
        "operational_state": operational_state,
        "publish_status": publish_status,
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
    if fallback_used is None:
        fallback_used = provider_status in {
            "partial_provider_success",
            "reused_after_provider_failure",
            "reused_same_content",
        }
    provider_outcome: dict[str, object] = {
        "status": provider_status,
        "fallback_used": fallback_used,
        "provider": "synthetic",
    }
    if series_attempts is not None:
        provider_outcome["series_attempts"] = series_attempts
    if cache_within_grace is not None:
        provider_outcome["cache_within_grace"] = cache_within_grace
    if availability_state is not None:
        provider_outcome["availability"] = {"state": availability_state}
    steps = [
        {"step": "harvester", "status": "failed" if "harvester" in (failed_steps or []) else "success", "provider_outcome": {
            **provider_outcome,
        }},
    ]
    (run_dir / "steps.jsonl").write_text(
        "\n".join(json.dumps(step) for step in steps) + "\n",
        encoding="utf-8",
    )


def test_manual_runs_do_not_satisfy_default_path_window(tmp_path: Path) -> None:
    assert DEFAULT_DEPLOYMENT_DATE == date(2026, 8, 22)
    _write_run(tmp_path, date(2026, 8, 22), 0, origin="manual")
    report = build_window_report(tmp_path)
    assert report["status"] == "PENDING"
    assert report["observed_runs"] == 0
    assert report["qualified_runs"] == 0
    assert report["consecutive_days"] == 0


def test_window_reports_complete_only_after_all_requirements(tmp_path: Path) -> None:
    start = date(2026, 8, 22)
    _write_run(
        tmp_path,
        start,
        0,
        status="partial_failure",
        execution_status="FAILED",
        provider_status="provider_failed_no_acceptable_fallback",
        operational_state="SYSTEM_FAILED",
        publish_status="NOT_PUBLISHED",
        failed_steps=["harvester"],
        blocked_steps=["judgment_layer"],
        tag="provider_failure",
    )
    _write_run(
        tmp_path,
        start + timedelta(days=1),
        1,
        status="success",
        execution_status="SUCCESS",
        provider_status="reused_after_provider_failure",
        operational_state="COMPLETED_DEGRADED",
        tag="provider_failure_stale",
        publish_status="COMMITTED",
    )
    _write_run(
        tmp_path,
        start + timedelta(days=2),
        2,
        provider_status="partial_provider_success",
        tag="schema_drift_parity_fixture",
    )
    parity_dir = tmp_path / "Data" / "harvester" / "provider_parity"
    parity_dir.mkdir(parents=True)
    (parity_dir / "window.json").write_text(
        json.dumps({"schema_version": "system.provider_parity_report.v1"}),
        encoding="utf-8",
    )
    for index in range(3, 15):
        _write_run(tmp_path, start + timedelta(days=index), index)
    report = build_window_report(tmp_path)
    assert report["status"] == "COMPLETE"
    assert report["consecutive_days"] == 14
    assert report["observed_runs"] == 15
    assert report["qualified_runs"] == 14
    assert report["scenario_by_run"]["daily_pipeline_20260823_120000_000001"][
        "provider_failure_with_fallback_qualified"
    ] is True
    assert all(report["scenarios"].values())


def test_provider_failure_without_fallback_is_recorded_but_not_a_blocker(tmp_path: Path) -> None:
    start = date(2026, 8, 22)
    _write_run(
        tmp_path,
        start,
        0,
        status="partial_failure",
        execution_status="FAILED",
        provider_status="provider_failed_no_acceptable_fallback",
        operational_state="SYSTEM_FAILED",
        publish_status="NOT_PUBLISHED",
        failed_steps=["harvester"],
        blocked_steps=["judgment_layer"],
    )
    _write_run(tmp_path, start + timedelta(days=1), 1)

    report = build_window_report(tmp_path)

    assert report["status"] == "PENDING"
    assert report["scenarios"]["provider_failure"] is True
    assert report["qualified_runs"] == 1
    assert report["consecutive_days"] == 1
    assert report["blockers"] == []
    assert report["non_qualified_runs"] == [
        {
            "run_id": "daily_pipeline_20260822_120000_000000",
            "date": "2026-08-22",
            "reasons": ["HARVESTER_NOT_COMMITTED", "CORE_CHAIN_INCOMPLETE"],
        }
    ]


def test_nested_provider_failure_with_fallback_stays_qualified(tmp_path: Path) -> None:
    run_day = date(2026, 8, 22)
    _write_run(
        tmp_path,
        run_day,
        0,
        provider_status="refreshed",
        fallback_used=True,
        series_attempts={
            "HYG": [
                {"outcome": "failed", "failure_class": "NETWORK", "error": "timeout"},
                {"outcome": "success", "failure_class": "NONE"},
            ]
        },
    )

    report = build_window_report(tmp_path)
    run_id = "daily_pipeline_20260822_120000_000000"

    assert report["scenarios"]["provider_failure"] is True
    assert report["scenario_by_run"][run_id]["fallback_or_carry_forward"] is True
    assert report["scenario_by_run"][run_id]["provider_failure_with_fallback_qualified"] is True
    assert report["qualification_by_run"][run_id]["qualified"] is True
    assert report["qualified_days"] == 1
    assert report["consecutive_days"] == 1
    assert report["blockers"] == []


def test_nested_stale_evidence_does_not_break_qualified_day(tmp_path: Path) -> None:
    run_day = date(2026, 8, 22)
    _write_run(
        tmp_path,
        run_day,
        0,
        provider_status="refreshed",
        fallback_used=True,
        cache_within_grace=False,
        availability_state="STALE",
    )

    report = build_window_report(tmp_path)
    run_id = "daily_pipeline_20260822_120000_000000"

    assert report["scenarios"]["cache_expiry_or_stale"] is True
    assert report["qualification_by_run"][run_id]["qualified"] is True
    assert report["qualified_days"] == 1
    assert report["consecutive_days"] == 1
    assert report["blockers"] == []
