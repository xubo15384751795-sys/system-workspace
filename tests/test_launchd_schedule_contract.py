from __future__ import annotations

import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _plist(name: str) -> dict:
    path = ROOT / "scripts" / "launchd" / name
    return plistlib.loads(path.read_bytes())


def test_harvester_job_is_acquisition_only_and_precedes_daily_run() -> None:
    harvester = _plist("com.system.daily-run-harvester.plist")
    args = harvester["ProgramArguments"]

    assert args[0:1] == ["/bin/bash"]
    assert args[-1].endswith("run_harvester_scheduled.sh")
    assert "daily_run.py" not in args
    assert harvester["StartCalendarInterval"] == {"Hour": 6, "Minute": 30}
    assert (ROOT / "scripts" / "run_harvester_scheduled.sh").is_file()


def test_postclose_job_cannot_reacquire_harvester() -> None:
    postclose = _plist("com.system.daily-run-harvester-postclose.plist")
    args = postclose["ProgramArguments"]

    assert args[-1] == "--skip-harvester"
