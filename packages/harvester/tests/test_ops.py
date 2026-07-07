from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from harvester.core.exporter import finalize_release
from harvester.ops import monitor_latest, next_release_id, run_daily_release, run_preflight
from tests.test_export_immutability import create_release, restore_permissions


def test_next_release_id_increments_for_release_date(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    (exports / "2026-05-10-r1").mkdir(parents=True)
    (exports / "2026-05-10-r2").mkdir()
    (exports / "2026-05-09-r9").mkdir()

    from datetime import date

    assert next_release_id(exports, release_date=date(2026, 5, 10)) == "2026-05-10-r3"


def test_preflight_reports_missing_fred_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("OPENBB_FRED_API_KEY", raising=False)
    exports = tmp_path / "exports"
    exports.mkdir()

    result = run_preflight(exports_root=exports, providers=["fred"])

    assert result.passed is False
    assert any(check.name == "fred_api_key" and not check.passed for check in result.checks)


def test_daily_release_writes_failure_report_when_preflight_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("OPENBB_FRED_API_KEY", raising=False)
    exports = tmp_path / "exports"
    exports.mkdir()

    result = run_daily_release(
        release_id="2026-05-10-r1",
        exports_root=exports,
        providers=["fred"],
        preflight=True,
    )

    assert result["status"] == "failed"
    failure_report = Path(result["failure_report"])
    assert failure_report.exists()
    payload = json.loads(failure_report.read_text(encoding="utf-8"))
    assert payload["reason"] == "preflight_failed"


def test_daily_release_finalizes_when_stage_and_finalize_succeed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test")
    exports = tmp_path / "exports"
    exports.mkdir()

    with patch("harvester.official.stage_complete_release") as stage, patch("harvester.ops.finalize_release") as finalize:
        stage.return_value = {"gate_passed": True}
        finalize.return_value.release_dir = exports / "2026-05-10-r1"
        finalize.return_value.verified_datasets = 3
        finalize.return_value.latest_path = exports / "latest"

        result = run_daily_release(
            release_id="2026-05-10-r1",
            exports_root=exports,
            providers=["fred"],
            preflight=True,
        )

    assert result["status"] == "finalized"
    assert result["verified_datasets"] == 3


def test_monitor_latest_reports_healthy_release(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    release_dir = create_release(exports)
    try:
        finalize_release("2026-04-26-r1", exports_root=exports, dry_run=False)

        result = monitor_latest(exports_root=exports, max_age_days=9999)

        assert result["status"] == "healthy"
        assert result["release_id"] == "2026-04-26-r1"
        assert not result["blockers"]
    finally:
        restore_permissions(release_dir)


def test_monitor_latest_reports_missing_latest(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()

    result = monitor_latest(exports_root=exports)

    assert result["status"] == "unhealthy"
    assert any(check["name"] == "latest_exists" and not check["passed"] for check in result["checks"])
