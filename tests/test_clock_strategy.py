from __future__ import annotations

import plistlib
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def test_daily_trigger_is_after_xnys_close_in_us_winter() -> None:
    new_york = ZoneInfo("America/New_York")
    singapore = ZoneInfo("Asia/Singapore")

    xnys_close = datetime(2026, 1, 5, 16, 0, tzinfo=new_york).astimezone(timezone.utc)
    next_trigger = datetime(2026, 1, 6, 7, 0, tzinfo=singapore).astimezone(timezone.utc)

    assert next_trigger > xnys_close
    assert (next_trigger - xnys_close).total_seconds() == 2 * 60 * 60


def test_daily_process_declares_utc_clock() -> None:
    wrapper = (ROOT / "scripts" / "run_daily_scheduled.sh").read_text(encoding="utf-8")
    plist = (ROOT / "scripts" / "launchd" / "com.system.daily-run.plist").read_text(encoding="utf-8")
    policy = (ROOT / "docs" / "operations" / "clock_strategy.md").read_text(encoding="utf-8")

    assert "export TZ=UTC" in wrapper
    assert "<key>TZ</key>" in plist
    assert "XNYS exchange session clock" in policy


def test_concurrent_harvester_is_disabled_until_phase_one_observation_gate() -> None:
    plist_path = ROOT / "scripts" / "launchd" / "com.system.daily-run.plist"
    payload = plistlib.loads(plist_path.read_bytes())

    assert payload["EnvironmentVariables"]["SYSTEM_HARVESTER_CONCURRENT"] == "0"
