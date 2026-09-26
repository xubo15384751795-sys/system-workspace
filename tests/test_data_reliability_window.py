"""Evidence-window verification must count only explicit scheduled bundles."""
from __future__ import annotations

import json
import os
import subprocess
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
    trigger_kind: str = "scheduled",
    scheduler_id: str = "com.system.daily-run",
    release_id: str = "release_test",
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
    authority_mode: str | None = None,
    generation_id: str | None = None,
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
    if authority_mode is not None:
        outcome["authority_mode"] = authority_mode
    if generation_id is not None:
        outcome["generation_id"] = generation_id
    manifest = {
        "run_id": run_id,
        "mode": "daily_pipeline",
        "tag": tag,
        "run_origin": origin,
        "trigger_kind": trigger_kind,
        "scheduler_kind": "launchd",
        "scheduler_id": scheduler_id,
        "schedule_id": "daily-test",
        "trigger_id": f"trigger-{index}",
        "host_id": "test-host",
        "release_id": release_id,
        "execution_identity": {
            "trigger_kind": trigger_kind,
            "scheduler_kind": "launchd",
            "scheduler_id": scheduler_id,
            "schedule_id": "daily-test",
            "trigger_id": f"trigger-{index}",
            "host_id": "test-host",
            "run_id": run_id,
            "release_id": release_id,
        },
        "started_at": f"{day.isoformat()}T12:00:00+00:00",
        "status": status,
        "outcome": outcome,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    contract_dir = root / "governance"
    contract_dir.mkdir(parents=True, exist_ok=True)
    contract = contract_dir / "reliability_window_contract.yaml"
    if not contract.exists():
        contract.write_text(
            "schema_version: test\n"
            "accepted_schedulers:\n"
            "  - com.system.daily-run\n"
            "accepted_release: release_test\n",
            encoding="utf-8",
        )
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


def _write_generation_admission(
    root: Path,
    generation_id: str,
    *,
    provider_decision: str = "ALLOW",
    freshness_verdict: str = "PASS",
    authority_verdict: str = "ALLOW",
    can_publish: bool = True,
    allows_decision_consumers: bool = True,
) -> None:
    generation_dir = root / "Output" / "generations" / generation_id
    generation_dir.mkdir(parents=True)
    (generation_dir / "manifest.json").write_text(
        json.dumps({"generation_id": generation_id, "status": "accepted"}),
        encoding="utf-8",
    )
    (generation_dir / "admission.json").write_text(
        json.dumps(
            {
                "generation_id": generation_id,
                "provider_decision": provider_decision,
                "freshness_verdict": freshness_verdict,
                "authority_verdict": authority_verdict,
                "can_publish": can_publish,
                "allows_decision_consumers": allows_decision_consumers,
            }
        ),
        encoding="utf-8",
    )


def test_manual_runs_do_not_satisfy_default_path_window(tmp_path: Path) -> None:
    assert DEFAULT_DEPLOYMENT_DATE == date(2026, 8, 22)
    _write_run(
        tmp_path,
        date(2026, 8, 22),
        0,
        origin="launchd",
        trigger_kind="manual",
    )
    report = build_window_report(tmp_path)
    assert report["status"] == "PENDING"
    assert report["observed_runs"] == 0
    assert report["qualified_runs"] == 0
    assert report["consecutive_days"] == 0


def test_documented_verifier_invocation_is_runnable_without_pythonpath(tmp_path: Path) -> None:
    """The evidence CLI must work from a clean shell, not only via pytest setup."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_data_reliability_window.py"

    result = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path)],
        cwd=script.parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["status"] == "PENDING"
    assert result.stderr == ""


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


def test_formal_target_mode_requires_authoritative_admitted_generation(tmp_path: Path) -> None:
    run_day = date(2026, 8, 22)
    run_id = "daily_pipeline_20260822_120000_000000"
    _write_run(
        tmp_path,
        run_day,
        0,
        authority_mode="authoritative",
        generation_id=run_id,
    )
    _write_generation_admission(tmp_path, run_id)

    report = build_window_report(tmp_path, formal_target=True)

    assert report["status"] == "PENDING"
    assert report["qualified_days"] == 1
    assert report["qualification_by_run"][run_id]["qualified"] is True
    assert all(report["qualification_by_run"][run_id]["formal_requirements"].values())


def test_formal_target_mode_rejects_diagnostic_generation(tmp_path: Path) -> None:
    run_day = date(2026, 8, 22)
    run_id = "daily_pipeline_20260822_120000_000000"
    _write_run(
        tmp_path,
        run_day,
        0,
        authority_mode="diagnostic",
        generation_id=run_id,
    )
    _write_generation_admission(
        tmp_path,
        run_id,
        authority_verdict="DIAGNOSTIC_ONLY",
        allows_decision_consumers=False,
    )

    report = build_window_report(tmp_path, formal_target=True)
    qualification = report["qualification_by_run"][run_id]

    assert report["qualified_days"] == 0
    assert qualification["qualified"] is False
    assert qualification["formal_requirements"]["authority_not_diagnostic_only"] is False
    assert "AUTHORITY_NOT_DIAGNOSTIC_ONLY" in qualification["reasons"]
