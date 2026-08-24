from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from orchestration.quality.contract_observation import (
    REQUIRED_CLEAN_DAYS,
    advance_observation_window,
    empty_observation_state,
    load_latest_contract_snapshot,
    record_launchd_observation,
)


def _advance(**overrides):
    payload = {
        "previous": None,
        "day": date(2026, 8, 24),
        "source": "launchd",
        "exit_code": 0,
        "contract_status": "PASS",
        "report_missing": False,
        "report_day": date(2026, 8, 24),
        "run_id": "daily-1",
        "policy_mode": "shadow",
    }
    payload.update(overrides)
    previous = payload.pop("previous")
    return advance_observation_window(previous, **payload)


def test_three_consecutive_launchd_days_are_reviewable_not_enforced() -> None:
    state = None
    day = date(2026, 8, 22)
    for offset in range(REQUIRED_CLEAN_DAYS):
        current = day + timedelta(days=offset)
        state = _advance(
            previous=state,
            day=current,
            report_day=current,
            run_id=f"daily-{offset}",
        )
    assert state["consecutive_clean_days"] == REQUIRED_CLEAN_DAYS
    assert state["ready_for_enforce_review"] is True
    assert state["mode"] == "shadow"
    assert state["enforce_changed"] is False


def test_block_or_missing_report_resets_the_window() -> None:
    first = _advance()
    blocked = _advance(previous=first, contract_status="BLOCK")
    assert blocked["consecutive_clean_days"] == 0
    assert blocked["reset_reason"] == "contract_block"
    assert blocked["ready_for_enforce_review"] is False

    missing = _advance(previous=first, report_missing=True, contract_status=None)
    assert missing["reset_reason"] == "missing_report"


def test_calendar_gap_restarts_the_count() -> None:
    first = _advance(day=date(2026, 8, 22), report_day=date(2026, 8, 22))
    gapped = _advance(
        previous=first,
        day=date(2026, 8, 24),
        report_day=date(2026, 8, 24),
    )
    assert gapped["consecutive_clean_days"] == 1
    assert gapped["last_event"] == "clean_day_start"


def test_manual_runs_do_not_count_or_reset() -> None:
    first = _advance()
    manual = _advance(previous=first, source="daily_run")
    assert manual["consecutive_clean_days"] == 1
    assert manual["last_event"] == "ignored_non_launchd"
    assert manual["ready_for_enforce_review"] is False


def test_stale_quality_report_does_not_count(tmp_path: Path) -> None:
    quality_dir = (
        tmp_path
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "quality_reports"
    )
    quality_dir.mkdir(parents=True)
    (quality_dir / "cross_asset_daily_panel.quality.json").write_text(
        '{"generated_at": "2026-08-20T00:00:00Z", "data_contract": {"status": "PASS", "mode": "shadow", "enforced": false}}',
        encoding="utf-8",
    )
    from datetime import UTC, datetime

    state = record_launchd_observation(
        workspace_root=tmp_path,
        output_root=tmp_path / "Output",
        outcome={"run_id": "daily-stale", "exit_code": 0},
        source="launchd",
        observed_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert state["reset_reason"] == "report_not_from_run_day"
    assert state["consecutive_clean_days"] == 0
    assert load_latest_contract_snapshot(tmp_path)["status"] == "PASS"
    assert empty_observation_state()["enforce_changed"] is False
