"""Acceptance tests for the single-entry ETF refresh and degraded state."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _write_panel(root: Path) -> None:
    path = root / "Data" / "harvester" / "exports" / "latest" / "data"
    path.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-12"]),
            "symbol": ["SPY"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1_000.0],
            "return_1d": [0.0],
            "return_5d": [0.0],
            "return_20d": [0.0],
            "return_60d": [0.0],
            "volatility_20d": [0.0],
            "drawdown_60d": [0.0],
        }
    ).to_parquet(path / "cross_asset_daily_panel.parquet", index=False)
    manifest = path.parent / "manifests" / "cross_asset_daily_panel.manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "release_id": "2026-08-12-r1",
                "provider_outcome": {
                    "status": "refreshed",
                    "provider": "yfinance",
                    "requested_count": 1,
                    "succeeded_count": 1,
                    "failed_count": 0,
                    "failed_series": [],
                },
            }
        ),
        encoding="utf-8",
    )


def test_refresh_reads_finalized_release_without_constructing_provider(
    tmp_path: Path, monkeypatch
) -> None:
    _write_panel(tmp_path)
    import harvester.operators.refresh_cross_asset_panel as refresh

    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(
        refresh,
        "HARVESTER_PANEL_PATH",
        tmp_path
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "data"
        / "cross_asset_daily_panel.parquet",
    )
    monkeypatch.setattr(
        refresh,
        "HARVESTER_EXPORTS_ROOT",
        tmp_path / "Data" / "harvester" / "exports",
    )

    import harvester.providers.etf_yfinance as etf_provider

    def no_provider(*_args, **_kwargs):
        raise AssertionError("refresh path must not construct yfinance provider")

    monkeypatch.setattr(etf_provider, "EtfYfinanceProvider", no_provider)
    panel, outcome = refresh._harvester_build(fetch_period="5d")

    assert not panel.empty
    assert outcome["status"] == "refreshed"
    assert (tmp_path / "Data" / "panels" / "cross_asset_daily_panel.parquet").exists()


def test_degraded_runoutcome_is_not_relabelled_as_system_failure() -> None:
    from system_runtime.run_outcome import RunOutcome

    outcome = RunOutcome(
        run_id="degraded-provider-run",
        spec_status="OK",
        execution_status="SUCCESS",
        degraded_steps=["refresh_cross_asset_panel"],
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
        reason_codes=["ADMISSION_REJECTED"],
        provider_status="reused_after_provider_failure",
    )

    assert outcome.exit_code == 4
    assert outcome.status == "degraded"
    assert outcome.operational_state == "COMPLETED_DEGRADED"
    assert outcome.to_dict()["provider_status"] == "reused_after_provider_failure"


def test_runoutcome_ready_and_system_failed_states_are_disjoint() -> None:
    from system_runtime.run_outcome import RunOutcome

    ready = RunOutcome(
        run_id="ready-run",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="PASS",
        publish_status="COMMITTED",
        authority_mode="authoritative",
    )
    failed = RunOutcome(
        run_id="failed-run",
        spec_status="OK",
        execution_status="FAILED",
        failed_steps=["harvester"],
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
        reason_codes=["REQUIRED_STEP_FAILED"],
    )

    assert ready.exit_code == 0
    assert ready.operational_state == "FRESH_READY"
    assert ready.status == "success"
    assert failed.exit_code == 3
    assert failed.operational_state == "SYSTEM_FAILED"
    assert failed.status == "partial_failure"


def test_expired_provider_cache_remains_blocked_and_high_severity(tmp_path: Path) -> None:
    from system_runtime.run_outcome import RunOutcome
    from verity.cli import daily_run

    outcome = RunOutcome(
        run_id="expired-provider-run",
        spec_status="OK",
        execution_status="SUCCESS",
        degraded_steps=["refresh_cross_asset_panel"],
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
        reason_codes=["ADMISSION_REJECTED"],
        provider_status="reused_after_provider_failure",
        provider_cache_within_grace=False,
    )
    daily_run.write_alert(
        [],
        [{"step": "refresh_cross_asset_panel", "status": "success", "degraded": True}],
        output_root=tmp_path,
        outcome=outcome.to_dict(),
    )
    alert = json.loads((tmp_path / "state" / "alerts" / "latest_alert.json").read_text())

    assert outcome.status == "partial_failure"
    assert outcome.operational_state == "COMPLETED_BLOCKED"
    assert alert["severity"] == "HIGH"
    assert alert["status"] == "partial_failure"


def test_pipeline_runner_preserves_structured_provider_outcome() -> None:
    from verity.runtime._pipeline_runner import run_subprocess_step

    result = run_subprocess_step(
        "refresh_cross_asset_panel",
        [
            "python3",
            "-c",
            (
                "import json; "
                "print('SYSTEM_STEP_OUTCOME=' + json.dumps({"
                "'status':'degraded', "
                "'provider_outcome':{'status':'reused_after_provider_failure'}"
                "}))"
            ),
        ],
    )

    assert result["status"] == "success"
    assert result["degraded"] is True
    assert result["provider_outcome"]["status"] == "reused_after_provider_failure"


def test_duplicate_degraded_notifications_are_suppressed(
    tmp_path: Path, monkeypatch
) -> None:
    from verity.runtime import _notify

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(_notify, "_suppression_reason", lambda: None)
    monkeypatch.setattr(_notify, "_notification_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(
        _notify,
        "notify_deviations",
        lambda title, deviations, **_kwargs: calls.append((title, "; ".join(deviations))) or True,
    )
    outcome = {
        "run_id": "run-1",
        "status": "degraded",
        "exit_code": 4,
        "admission_verdict": "BLOCK",
        "publish_status": "NOT_PUBLISHED",
        "provider_status": "reused_after_provider_failure",
        "reason_codes": ["ADMISSION_REJECTED"],
    }

    _notify.notify_daily_run_result(
        status="degraded",
        failed_steps=[],
        warnings=["provider cooldown"],
        outcome=outcome,
    )
    _notify.notify_daily_run_result(
        status="degraded",
        failed_steps=[],
        warnings=["provider cooldown changed age"],
        outcome={**outcome, "run_id": "run-2"},
    )

    assert len(calls) == 1
    assert calls[0][0] == "System daily_run warnings"


def test_duplicate_fingerprint_reescalates_after_consecutive_days(
    tmp_path: Path, monkeypatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from verity.runtime import _notify

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(_notify, "_suppression_reason", lambda: None)
    monkeypatch.setattr(_notify, "_notification_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setenv("NOTIFY_REPEAT_ESCALATION_DAYS", "3")
    monkeypatch.setattr(
        _notify,
        "notify_deviations",
        lambda title, deviations, **_kwargs: calls.append((title, "; ".join(deviations))) or True,
    )
    start = datetime(2026, 8, 1, 1, tzinfo=UTC)
    moments = iter(start + timedelta(days=offset) for offset in range(3))
    monkeypatch.setattr(_notify, "_dedup_now", lambda: next(moments))
    outcome = {
        "run_id": "run-repeat",
        "status": "degraded",
        "exit_code": 4,
        "admission_verdict": "BLOCK",
        "publish_status": "NOT_PUBLISHED",
        "provider_status": "reused_after_provider_failure",
        "reason_codes": ["ADMISSION_REJECTED"],
    }

    for _ in range(3):
        _notify.notify_daily_run_result(
            status="degraded",
            failed_steps=[],
            warnings=["provider cooldown"],
            outcome=outcome,
        )

    assert len(calls) == 2
