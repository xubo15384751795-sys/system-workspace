#!/usr/bin/env python3
"""Read-only reconciliation of System/Horizon LaunchAgent records."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_LABELS = (
    "com.system.daily-run",
    "com.horizon.daily",
    "com.system.paper-watch",
    "com.system.main-ci-watch",
    "com.system.daily-run-harvester",
    "com.system.daily-run-harvester-postclose",
    "com.system.daily-run-deadman",
)
DISABLED_LABELS = frozenset(
    {"com.system.daily-run-harvester", "com.system.daily-run-harvester-postclose"}
)


def _schedule(payload: dict[str, Any]) -> list[str]:
    value = payload.get("StartCalendarInterval")
    entries = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in entries:
        if not isinstance(item, dict) or "Hour" not in item:
            continue
        try:
            hour = int(item["Hour"])
            minute = int(item.get("Minute", 0))
        except (TypeError, ValueError):
            continue
        result.append(f"{hour:02d}:{minute:02d}")
    return result


def _launchctl_snapshot(label: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"status": "unavailable"}
    if result.returncode != 0:
        return {"status": "not_loaded"}
    text = result.stdout
    snapshot: dict[str, Any] = {"status": "loaded"}
    for key, pattern in {
        "state": r"^\s*state = ([^\n]+)",
        "runs": r"^\s*runs = (\d+)",
        "last_exit_code": r"^\s*last exit code = ([^\n]+)",
    }.items():
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            continue
        value = match.group(1).strip()
        snapshot[key] = int(value) if key == "runs" else value
    return snapshot


def audit(
    *,
    installed_dir: Path | None = None,
    include_launchctl: bool = True,
) -> dict[str, Any]:
    installed = (installed_dir or Path.home() / "Library/LaunchAgents").resolve()
    records: dict[str, Any] = {}
    violations: list[str] = []
    for label in EXPECTED_LABELS:
        path = installed / f"{label}.plist"
        record: dict[str, Any] = {
            "installed": path.is_file(),
            "path": str(path),
            "expected_disabled": label in DISABLED_LABELS,
        }
        if path.is_file():
            try:
                payload = plistlib.loads(path.read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException) as exc:
                record["plist_error"] = type(exc).__name__
                violations.append(f"{label}: invalid plist")
            else:
                record["plist_disabled"] = payload.get("Disabled") is True
                record["schedule"] = _schedule(payload)
                if label in DISABLED_LABELS and record["plist_disabled"] is not True:
                    violations.append(f"{label}: expected Disabled=true")
                if label not in DISABLED_LABELS and record["plist_disabled"] is True:
                    violations.append(f"{label}: unexpectedly disabled")
        else:
            violations.append(f"{label}: installed plist missing")
        record["launchctl"] = (
            _launchctl_snapshot(label) if include_launchctl else {"status": "not_checked"}
        )
        launch_status = record["launchctl"].get("status")
        if label in DISABLED_LABELS:
            if launch_status == "loaded":
                violations.append(f"{label}: disabled record is loaded")
        elif launch_status not in {"loaded", "not_checked"}:
            violations.append(f"{label}: expected loaded launchd service, got {launch_status}")
        records[label] = record
    return {
        "schema_version": "system.launchd_reconciliation.v1",
        "installed_dir": str(installed),
        "labels": list(EXPECTED_LABELS),
        "records": records,
        "violations": violations,
        "status": "PASS" if not violations else "BLOCKED",
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-dir", type=Path)
    parser.add_argument("--no-launchctl", action="store_true")
    parser.add_argument("--fail-on-drift", action="store_true")
    args = parser.parse_args(argv)
    result = audit(
        installed_dir=args.installed_dir,
        include_launchctl=not args.no_launchctl,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if args.fail_on_drift and result["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
