#!/usr/bin/env python3
"""Assert that clean-checkout tests do not materialize ``Data/`` or ``Output/``.

The state file belongs in the CI runner's temporary directory, not in the
workspace.  DVC pointers and checked-in fixture files under ``Data/`` are
source-controlled inputs, not materialized operator data, so they are allowed.
``os.path.lexists`` is intentional: a broken symlink is still a workspace
surface and must not be treated as absent.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "system.clean_checkout_boundary.v2"
SURFACES = ("Data", "Output")
DEFAULT_ROOT = Path(__file__).resolve().parents[3]


def _tracked_paths(root: Path, name: str) -> set[str]:
    """Return source-controlled paths below a workspace surface."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", f"{name}/"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return set()
    if completed.returncode != 0:
        return set()
    return {
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    }


def _operator_surface_exists(root: Path, name: str) -> bool:
    surface = root / name
    if not os.path.lexists(surface):
        return False
    if surface.is_symlink() or not surface.is_dir():
        return True

    tracked = _tracked_paths(root, name)
    if not tracked:
        return True

    for candidate in surface.rglob("*"):
        if not os.path.lexists(candidate):
            continue
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_dir() and not candidate.is_symlink():
            if not any(
                tracked_path.startswith(relative + "/")
                for tracked_path in tracked
            ):
                return True
        elif relative not in tracked:
            return True
    return False


def _surface_state(root: Path) -> dict[str, bool]:
    return {
        name: _operator_surface_exists(root, name)
        for name in SURFACES
    }


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _failure_messages(state: dict[str, bool], *, prefix: str) -> list[str]:
    return [
        f"{prefix}: {name}/ exists"
        for name, exists in state.items()
        if exists
    ]


def run_before(root: Path, state_file: Path) -> int:
    """Record the clean-checkout baseline and fail on pre-existing surfaces."""
    root = root.resolve()
    if not root.is_dir():
        print(f"clean-checkout boundary FAIL: root is not a directory: {root}")
        return 2

    before = _surface_state(root)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "before": before,
    }
    failures = _failure_messages(before, prefix="before test run")
    payload["verdict"] = "FAIL" if failures else "PASS"
    _write_state(state_file, payload)
    if failures:
        print(json.dumps({"check": SCHEMA_VERSION, **payload}, indent=2))
        return 1

    print(json.dumps({"check": SCHEMA_VERSION, **payload}, indent=2))
    return 0


def _load_state(state_file: Path, root: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"clean-checkout boundary FAIL: cannot read state file: {exc}")
        return None
    if not isinstance(payload, dict):
        print("clean-checkout boundary FAIL: state file is not an object")
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        print("clean-checkout boundary FAIL: unsupported state schema")
        return None
    if payload.get("root") != str(root.resolve()):
        print("clean-checkout boundary FAIL: state root does not match current root")
        return None
    before = payload.get("before")
    if not isinstance(before, dict) or any(
        not isinstance(before.get(name), bool) for name in SURFACES
    ):
        print("clean-checkout boundary FAIL: malformed before state")
        return None
    return payload


def run_after(root: Path, state_file: Path) -> int:
    """Verify the baseline and post-test workspace surfaces are both absent."""
    root = root.resolve()
    payload = _load_state(state_file, root)
    if payload is None:
        return 2

    before = {name: bool(payload["before"][name]) for name in SURFACES}
    after = _surface_state(root)
    failures = _failure_messages(before, prefix="before test run")
    failures.extend(_failure_messages(after, prefix="after test run"))
    payload["after"] = after
    payload["verdict"] = "FAIL" if failures else "PASS"
    _write_state(state_file, payload)
    print(json.dumps({"check": SCHEMA_VERSION, **payload}, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    args = parser.parse_args()
    if args.phase == "before":
        return run_before(args.root, args.state_file)
    return run_after(args.root, args.state_file)


if __name__ == "__main__":
    sys.exit(main())
