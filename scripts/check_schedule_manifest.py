#!/usr/bin/env python3
"""Read-only audit of tracked and installed launchd schedule records."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.parsers.expat import ExpatError

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_LABEL = "com.system.daily-run"
LEGACY_LABELS = (
    "com.system.daily-run-harvester",
    "com.system.daily-run-harvester-postclose",
)


def _load(path: Path) -> dict[str, Any]:
    return plistlib.loads(path.read_bytes())


def _is_python_313(candidate: Any) -> bool:
    """Validate an installed interpreter without importing project code."""
    if not isinstance(candidate, str) or not candidate or candidate == "__SYSTEM_PYTHON__":
        return candidate == "__SYSTEM_PYTHON__"
    path = Path(candidate)
    if not path.is_file() or not os.access(path, os.X_OK):
        return False
    try:
        result = subprocess.run(
            [str(path), "-c", "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _canonical_semantic_match(installed: dict[str, Any], rendered: dict[str, Any]) -> bool:
    """Compare canonical plist semantics while allowing a resolved 3.13 path.

    The tracked plist deliberately keeps ``__SYSTEM_PYTHON__`` as a portable
    placeholder, while installation renders a concrete interpreter path.  A
    valid Python 3.13 path is semantically equivalent; a different runtime is
    still drift and is reported separately.
    """
    if installed == rendered:
        return True
    expected_env = rendered.get("EnvironmentVariables") or {}
    installed_env = installed.get("EnvironmentVariables") or {}
    if expected_env.get("PYTHON") != "__SYSTEM_PYTHON__":
        return False
    if not _is_python_313(installed_env.get("PYTHON")):
        return False
    expected_without_python = dict(expected_env)
    installed_without_python = dict(installed_env)
    expected_without_python.pop("PYTHON", None)
    installed_without_python.pop("PYTHON", None)
    expected_copy = dict(rendered)
    installed_copy = dict(installed)
    expected_copy["EnvironmentVariables"] = expected_without_python
    installed_copy["EnvironmentVariables"] = installed_without_python
    return installed_copy == expected_copy


def _legacy_semantic_match(installed: dict[str, Any], tracked: dict[str, Any]) -> bool:
    """Allow a concrete Python 3.13 path in a disabled legacy record.

    Legacy plists are intentionally tracked with ``__SYSTEM_PYTHON__`` so the
    record remains portable.  Installation renders that one argument to a
    concrete interpreter path.  The record is still semantically identical
    when the resolved interpreter is Python 3.13 and every other field matches.
    """
    if installed == tracked:
        return True
    expected_args = tracked.get("ProgramArguments") or []
    installed_args = installed.get("ProgramArguments") or []
    if (
        not isinstance(expected_args, list)
        or not isinstance(installed_args, list)
        or len(expected_args) != len(installed_args)
        or not expected_args
        or expected_args[0] != "__SYSTEM_PYTHON__"
        or not _is_python_313(installed_args[0])
    ):
        return False
    expected_copy = dict(tracked)
    installed_copy = dict(installed)
    expected_copy["ProgramArguments"] = expected_args[1:]
    installed_copy["ProgramArguments"] = installed_args[1:]
    return installed_copy == expected_copy


def _render_canonical(root: Path, paper_root: Path, horizon_root: Path) -> dict[str, Any]:
    path = root / "scripts/launchd/com.system.daily-run.plist"
    payload = path.read_text(encoding="utf-8")
    for token, value in {
        "__SYSTEM_ROOT__": str(root),
        "__PAPER_ROOT__": str(paper_root),
        "__HORIZON_ROOT__": str(horizon_root),
    }.items():
        payload = payload.replace(token, value)
    return plistlib.loads(payload.encode("utf-8"))


def _program_arguments_ok(root: Path, payload: dict[str, Any]) -> list[str]:
    arguments = payload.get("ProgramArguments") or []
    violations: list[str] = []
    if not isinstance(arguments, list) or not arguments:
        return ["ProgramArguments missing or empty"]
    for index, value in enumerate(arguments):
        if not isinstance(value, str) or not value:
            violations.append(f"ProgramArguments[{index}] is not a non-empty string")
    executable = arguments[0] if arguments else ""
    if executable.startswith("/"):
        executable_path = Path(executable)
        if not executable_path.is_file():
            violations.append(f"executable missing: {executable}")
        elif not os.access(executable_path, os.X_OK):
            violations.append(f"executable not executable: {executable}")
    for index, value in enumerate(arguments[1:], start=1):
        if not isinstance(value, str) or not value.startswith("/"):
            continue
        target = Path(value)
        if target.suffix not in {".py", ".sh"}:
            continue
        if not target.is_file():
            violations.append(f"ProgramArguments[{index}] target missing: {value}")
    if "run_daily_scheduled.sh" in arguments:
        wrapper = root / "scripts/run_daily_scheduled.sh"
        if not wrapper.is_file() or not wrapper.stat().st_mode & 0o111:
            violations.append(f"daily wrapper missing or not executable: {wrapper}")
    return violations


def _launchctl_state(label: str) -> str:
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{__import__('os').getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return "loaded" if result.returncode == 0 else "not_loaded"


def audit(
    *,
    root: Path = ROOT,
    installed_dir: Path | None = None,
    paper_root: Path | None = None,
    horizon_root: Path | None = None,
    include_launchctl: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    installed = (installed_dir or Path.home() / "Library/LaunchAgents").resolve()
    rendered = _render_canonical(
        root,
        (paper_root or root.parent / "Paper").resolve(),
        (horizon_root or root.parent / "Horizon").resolve(),
    )
    records: dict[str, Any] = {}
    violations: list[str] = []
    tracked_canonical = root / "scripts/launchd/com.system.daily-run.plist"
    records[CANONICAL_LABEL] = {
        "tracked": str(tracked_canonical),
        "installed": str(installed / f"{CANONICAL_LABEL}.plist"),
        "authoritative": True,
        "tracked_program_arguments": rendered.get("ProgramArguments", []),
        "installed_exists": (installed / f"{CANONICAL_LABEL}.plist").is_file(),
        "launchctl": _launchctl_state(CANONICAL_LABEL) if include_launchctl else "not_checked",
    }
    violations.extend(
        f"{CANONICAL_LABEL}: {message}" for message in _program_arguments_ok(root, rendered)
    )
    installed_path = installed / f"{CANONICAL_LABEL}.plist"
    if installed_path.is_file():
        installed_payload = _load(installed_path)
        installed_python = (installed_payload.get("EnvironmentVariables") or {}).get("PYTHON")
        records[CANONICAL_LABEL]["installed_python"] = installed_python
        records[CANONICAL_LABEL]["python_313"] = _is_python_313(installed_python)
        records[CANONICAL_LABEL]["semantic_match"] = _canonical_semantic_match(
            installed_payload, rendered
        )
        if not records[CANONICAL_LABEL]["semantic_match"]:
            violations.append(f"{CANONICAL_LABEL}: installed plist differs from rendered tracked plist")
        if not records[CANONICAL_LABEL]["python_313"]:
            violations.append(f"{CANONICAL_LABEL}: installed PYTHON is not Python 3.13")
        violations.extend(
            f"{CANONICAL_LABEL}: installed {message}"
            for message in _program_arguments_ok(root, installed_payload)
        )
    else:
        violations.append(f"{CANONICAL_LABEL}: installed plist missing")
        records[CANONICAL_LABEL]["semantic_match"] = False
        records[CANONICAL_LABEL]["python_313"] = False

    for label in LEGACY_LABELS:
        tracked = root / "scripts/launchd" / f"{label}.plist"
        path = installed / f"{label}.plist"
        payload = _load(tracked)
        entry = {
            "tracked": str(tracked),
            "installed": str(path),
            "authoritative": False,
            "tracked_disabled": payload.get("Disabled") is True,
            "installed_exists": path.is_file(),
            "launchctl": _launchctl_state(label) if include_launchctl else "not_checked",
        }
        records[label] = entry
        if payload.get("Disabled") is not True:
            violations.append(f"{label}: tracked legacy record is not Disabled=true")
        if path.is_file():
            try:
                installed_payload = _load(path)
            except (OSError, ValueError, plistlib.InvalidFileException, ExpatError) as exc:
                entry["semantic_match"] = False
                violations.append(f"{label}: installed plist is invalid ({exc})")
                continue
            entry["semantic_match"] = _legacy_semantic_match(installed_payload, payload)
            if not entry["semantic_match"]:
                violations.append(f"{label}: installed plist differs from tracked disabled record")
            if installed_payload.get("Disabled") is not True:
                violations.append(f"{label}: installed legacy record is not Disabled=true")
        else:
            entry["semantic_match"] = False
            violations.append(f"{label}: installed disabled record missing")
        violations.extend(f"{label}: {message}" for message in _program_arguments_ok(root, payload))

    horizon_path = installed / "com.horizon.daily.plist"
    horizon_entry: dict[str, Any] = {
        "installed": str(horizon_path),
        "exists": horizon_path.is_file(),
        "authoritative_for_system_core": False,
    }
    if horizon_path.is_file():
        horizon_payload = _load(horizon_path)
        args = horizon_payload.get("ProgramArguments") or []
        horizon_entry["program_arguments"] = args
        independent = "horizon" in " ".join(str(item) for item in args).lower()
        points_to_daily = "daily" in " ".join(str(item) for item in args).lower() and not independent
        horizon_entry["independent"] = independent and not points_to_daily
        if not horizon_entry["independent"]:
            violations.append("com.horizon.daily: does not have an independent horizon entrypoint")
    records["com.horizon.daily"] = horizon_entry

    status = "PASS" if not violations else "BLOCKED"
    return {
        "schema_version": "system.schedule_manifest.v1",
        "root": str(root),
        "installed_dir": str(installed),
        "authoritative_labels": [CANONICAL_LABEL],
        "legacy_labels": list(LEGACY_LABELS),
        "records": records,
        "violations": violations,
        "status": status,
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--installed-dir", type=Path)
    parser.add_argument("--include-launchctl", action="store_true")
    parser.add_argument("--fail-on-drift", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = audit(
            root=args.root,
            installed_dir=args.installed_dir,
            include_launchctl=args.include_launchctl,
        )
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        print(f"schedule manifest: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if args.fail_on_drift and result["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
