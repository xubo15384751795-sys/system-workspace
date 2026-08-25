from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import system_runtime.daily_heartbeat as heartbeat
from system_runtime.daily_heartbeat import (
    check_daily_run_heartbeat,
    heartbeat_path,
    write_daily_run_heartbeat,
)


def test_daily_run_heartbeat_is_atomic_and_checkable(tmp_path: Path) -> None:
    observed = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)
    outcome = {
        "run_id": "daily-test-001",
        "status": "partial_failure",
        "exit_code": 3,
        "operational_state": "SYSTEM_FAILED",
    }

    payload = write_daily_run_heartbeat(
        outcome,
        output_root=tmp_path,
        source="test",
        observed_at=observed,
    )
    assert heartbeat_path(tmp_path).is_file()
    assert payload["run_id"] == "daily-test-001"
    assert check_daily_run_heartbeat(
        output_root=tmp_path,
        now=observed + timedelta(hours=25),
        max_age_hours=26,
    )["status"] == "PASS"
    stale = check_daily_run_heartbeat(
        output_root=tmp_path,
        now=observed + timedelta(hours=27),
        max_age_hours=26,
    )
    assert stale["status"] == "ALERT"
    assert stale["reason"] == "heartbeat_stale"


def test_missing_daily_run_heartbeat_is_alert(tmp_path: Path) -> None:
    report = check_daily_run_heartbeat(output_root=tmp_path)
    assert report["status"] == "ALERT"
    assert report["reason"] == "heartbeat_missing"


def test_healthchecks_sink_status_is_recorded_after_local_write(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "HEALTHCHECKS_DAILY_RUN_URL", "https://hc-ping.com/test-heartbeat"
    )
    monkeypatch.setattr(heartbeat, "_remote_sinks_disabled", lambda: False)
    monkeypatch.setattr(heartbeat, "_ping_healthchecks", lambda _url: True)

    payload = write_daily_run_heartbeat(
        {"run_id": "daily-healthchecks", "status": "success", "exit_code": 0},
        output_root=tmp_path,
        source="test",
        observed_at=datetime(2026, 8, 22, 1, 0, tzinfo=UTC),
    )

    assert payload["healthchecks"] == "sent"
    assert '"healthchecks": "sent"' in heartbeat_path(tmp_path).read_text()
