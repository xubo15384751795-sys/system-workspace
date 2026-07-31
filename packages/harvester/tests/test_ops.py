from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from harvester.core.exporter import finalize_release
from harvester.ops import (
    monitor_latest,
    next_release_id,
    run_daily_release,
    run_preflight,
)

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


def test_daily_release_writes_failure_report_on_systemexit(tmp_path: Path, monkeypatch) -> None:
    """Phase 0.2: a SystemExit during staging must still produce a failure
    report. Previously only ``except Exception`` caught it; SystemExit (a
    BaseException) escaped, leaving no report - the six-day blind spot."""
    monkeypatch.setenv("FRED_API_KEY", "test")
    exports = tmp_path / "exports"
    exports.mkdir()

    def _raise(*a, **kw):
        raise SystemExit(1)

    with patch("harvester.official.stage_complete_release", side_effect=_raise), \
         patch("harvester.ops.finalize_release"):
        result = run_daily_release(
            release_id="2026-05-10-r1",
            exports_root=exports,
            providers=["fred"],
            preflight=False,
        )

    assert result["status"] == "failed"
    assert result["reason"] == "release_failed"
    # The failure report file must exist despite SystemExit.
    report = exports / ".failures" / "2026-05-10-r1.release_failed.json"
    assert report.exists(), "SystemExit failure must still write a report"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert "SystemExit" in payload["error"]


def test_daily_release_writes_failure_report_on_runtime_error(tmp_path: Path, monkeypatch) -> None:
    """A RuntimeError during staging must produce a failure report."""
    monkeypatch.setenv("FRED_API_KEY", "test")
    exports = tmp_path / "exports"
    exports.mkdir()

    def _raise(*a, **kw):
        raise RuntimeError("provider 429")

    with patch("harvester.official.stage_complete_release", side_effect=_raise), \
         patch("harvester.ops.finalize_release"):
        result = run_daily_release(
            release_id="2026-05-10-r2",
            exports_root=exports,
            providers=["fred"],
            preflight=False,
        )

    assert result["status"] == "failed"
    report = exports / ".failures" / "2026-05-10-r2.release_failed.json"
    assert report.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert "provider 429" in payload["error"]


def test_write_failure_report_does_not_raise_on_unwritable_path(tmp_path: Path, capsys) -> None:
    """Phase 0.2: _write_failure_report swallows OSError and prints to stderr."""
    from harvester.ops import _write_failure_report

    # Point at a path whose parent cannot be created (root-locked).
    unwritable = Path("/proc/cannot-create-here")
    # Should not raise.
    _write_failure_report(unwritable, "r1", "test", {"error": "boom"})
    captured = capsys.readouterr()
    assert "FAILED to write failure report" in captured.err


def test_daily_release_reuses_same_day_finalized(tmp_path: Path, monkeypatch) -> None:
    """Phase 2.1: if latest points to a finalized release for today, the
    release is reused (status=reused) with no network calls."""
    from harvester.ops import _check_same_day_reuse

    exports = tmp_path / "exports"
    release_dir = exports / "20260718-r1"
    release_dir.mkdir(parents=True)
    (release_dir / ".finalized").write_text("ok", encoding="utf-8")
    (release_dir / "catalog.json").write_text(json.dumps({
        "release_id": "20260718-r1",
        "as_of_date": "2026-07-18",
    }), encoding="utf-8")
    (exports / "latest").symlink_to(release_dir)

    result = _check_same_day_reuse(exports, "2026-07-18")
    assert result is not None
    assert result["status"] == "reused"
    assert result["reason"] == "same_day_finalized_release_exists"


def test_run_daily_release_reuses_when_release_id_empty(tmp_path: Path, monkeypatch) -> None:
    """Empty release_id (CLI default) must trigger same-day reuse — not ``is None`` only."""
    monkeypatch.setenv("FRED_API_KEY", "test")
    exports = tmp_path / "exports"
    release_dir = exports / "2026-07-18-r1"
    release_dir.mkdir(parents=True)
    (release_dir / ".finalized").write_text("ok", encoding="utf-8")
    (release_dir / "catalog.json").write_text(
        json.dumps({"release_id": "2026-07-18-r1", "as_of_date": "2026-07-18"}),
        encoding="utf-8",
    )
    (exports / "latest").symlink_to(release_dir)

    with patch("harvester.official.stage_complete_release") as stage:
        result = run_daily_release(
            as_of_date="2026-07-18",
            exports_root=exports,
            providers=["fred"],
            preflight=False,
        )
        stage.assert_not_called()

    assert result["status"] == "reused"
    assert result["release_id"] == "2026-07-18-r1"


def test_daily_release_reuses_dashed_release_id_without_catalog_as_of(tmp_path: Path) -> None:
    """Reuse must match YYYY-MM-DD-rN even when catalog omits as_of_date."""
    from harvester.ops import _check_same_day_reuse

    exports = tmp_path / "exports"
    release_dir = exports / "2026-07-18-r2"
    release_dir.mkdir(parents=True)
    (release_dir / ".finalized").write_text("ok", encoding="utf-8")
    (release_dir / "catalog.json").write_text(
        json.dumps({"release_id": "2026-07-18-r2"}),
        encoding="utf-8",
    )
    (exports / "latest").symlink_to(release_dir)

    result = _check_same_day_reuse(exports, "2026-07-18")
    assert result is not None
    assert result["status"] == "reused"


def test_daily_release_does_not_reuse_stale_day(tmp_path: Path) -> None:
    """A finalized release for a DIFFERENT day must not be reused."""
    from harvester.ops import _check_same_day_reuse

    exports = tmp_path / "exports"
    release_dir = exports / "20260715-r1"
    release_dir.mkdir(parents=True)
    (release_dir / ".finalized").write_text("ok", encoding="utf-8")
    (release_dir / "catalog.json").write_text(json.dumps({
        "release_id": "20260715-r1",
        "as_of_date": "2026-07-15",
    }), encoding="utf-8")
    (exports / "latest").symlink_to(release_dir)

    assert _check_same_day_reuse(exports, "2026-07-18") is None


def test_daily_release_does_not_reuse_unfinalized(tmp_path: Path) -> None:
    """An unfinalized same-day release must not be reused."""
    from harvester.ops import _check_same_day_reuse

    exports = tmp_path / "exports"
    release_dir = exports / "20260718-r1"
    release_dir.mkdir(parents=True)
    # No .finalized marker.
    (release_dir / "catalog.json").write_text(json.dumps({
        "release_id": "20260718-r1",
        "as_of_date": "2026-07-18",
    }), encoding="utf-8")
    (exports / "latest").symlink_to(release_dir)

    assert _check_same_day_reuse(exports, "2026-07-18") is None


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


def test_cli_daily_release_exits_zero_on_same_day_reuse(monkeypatch) -> None:
    """The same-day short-circuit is a successful no-op. Exiting non-zero made
    the 2nd/3rd nightly schedules report a hard failure and block every
    downstream pipeline step."""
    # Importing harvester.cli calls load_dotenv() at import time; swap in a
    # copy of the environment so those credentials cannot leak into tests that
    # assert on a missing API key.
    monkeypatch.setattr(os, "environ", dict(os.environ))

    from harvester.cli import main

    for status, expected in [("finalized", 0), ("reused", 0), ("failed", 1)]:
        with patch("harvester.cli.run_daily_release", return_value={"status": status}):
            assert main(["daily-release"]) == expected, status
