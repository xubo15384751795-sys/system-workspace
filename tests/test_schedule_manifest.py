"""Tracked/installed launchd schedule contract tests."""
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

from scripts.check_schedule_manifest import audit

ROOT = Path(__file__).resolve().parents[1]


def _write_installed(tmp_path: Path) -> Path:
    installed = tmp_path / "LaunchAgents"
    installed.mkdir()
    source = ROOT / "scripts/launchd"
    canonical = source / "com.system.daily-run.plist"
    text = canonical.read_text(encoding="utf-8")
    for token, value in {
        "__SYSTEM_ROOT__": str(ROOT),
        "__PAPER_ROOT__": str(ROOT.parent / "Paper"),
        "__HORIZON_ROOT__": str(ROOT.parent / "Horizon"),
    }.items():
        text = text.replace(token, value)
    (installed / canonical.name).write_bytes(
        plistlib.dumps(plistlib.loads(text.encode("utf-8")))
    )
    for name in (
        "com.system.daily-run-harvester.plist",
        "com.system.daily-run-harvester-postclose.plist",
    ):
        (installed / name).write_bytes((source / name).read_bytes())
    return installed


def test_schedule_audit_passes_rendered_disabled_records(tmp_path: Path) -> None:
    result = audit(root=ROOT, installed_dir=_write_installed(tmp_path))

    assert result["status"] == "PASS", result["violations"]
    assert result["authoritative_labels"] == ["com.system.daily-run"]
    assert result["records"]["com.horizon.daily"]["exists"] is False
    wrapper = (ROOT / "scripts" / "run_daily_scheduled.sh").read_text(encoding="utf-8")
    assert "SYSTEM_SCHEDULE_LABEL" in wrapper
    assert "SYSTEM_SCHEDULE_CALENDAR" in wrapper
    assert 'run_dagster_daily.sh" "$@"' in wrapper


def test_schedule_audit_detects_installed_drift(tmp_path: Path) -> None:
    installed = _write_installed(tmp_path)
    path = installed / "com.system.daily-run.plist"
    payload = plistlib.loads(path.read_bytes())
    payload["StartCalendarInterval"]["Hour"] = 8
    path.write_bytes(plistlib.dumps(payload))

    result = audit(root=ROOT, installed_dir=installed)

    assert result["status"] == "BLOCKED"
    assert any("installed plist differs" in item for item in result["violations"])


def test_schedule_audit_accepts_resolved_python_313_path(tmp_path: Path) -> None:
    installed = _write_installed(tmp_path)
    path = installed / "com.system.daily-run.plist"
    payload = plistlib.loads(path.read_bytes())
    payload["EnvironmentVariables"]["PYTHON"] = sys.executable
    path.write_bytes(plistlib.dumps(payload))

    result = audit(root=ROOT, installed_dir=installed)

    assert result["records"]["com.system.daily-run"]["python_313"] is True
    assert result["records"]["com.system.daily-run"]["semantic_match"] is True
    assert result["status"] == "PASS", result["violations"]


def test_schedule_audit_accepts_resolved_python_313_wrapper_path(tmp_path: Path) -> None:
    installed = _write_installed(tmp_path)
    path = installed / "com.system.daily-run.plist"
    payload = plistlib.loads(path.read_bytes())
    payload["ProgramArguments"][0] = sys.executable
    payload["EnvironmentVariables"]["PYTHON"] = sys.executable
    path.write_bytes(plistlib.dumps(payload))

    result = audit(root=ROOT, installed_dir=installed)

    assert result["records"]["com.system.daily-run"]["semantic_match"] is True
    assert result["status"] == "PASS", result["violations"]


def test_schedule_audit_accepts_resolved_python_313_path_for_legacy_records(tmp_path: Path) -> None:
    installed = _write_installed(tmp_path)
    for name in (
        "com.system.daily-run-harvester.plist",
        "com.system.daily-run-harvester-postclose.plist",
    ):
        path = installed / name
        payload = plistlib.loads(path.read_bytes())
        payload["ProgramArguments"][0] = sys.executable
        path.write_bytes(plistlib.dumps(payload))

    result = audit(root=ROOT, installed_dir=installed)

    assert result["records"]["com.system.daily-run-harvester"]["semantic_match"] is True
    assert result["records"]["com.system.daily-run-harvester-postclose"]["semantic_match"] is True
    assert result["status"] == "PASS", result["violations"]


def test_schedule_audit_rejects_missing_script_target(tmp_path: Path) -> None:
    installed = _write_installed(tmp_path)
    path = installed / "com.system.daily-run.plist"
    payload = plistlib.loads(path.read_bytes())
    payload["ProgramArguments"][1] = str(tmp_path / "missing-runner.sh")
    path.write_bytes(plistlib.dumps(payload))

    result = audit(root=ROOT, installed_dir=installed)

    assert result["status"] == "BLOCKED"
    assert any("target missing" in item for item in result["violations"])
