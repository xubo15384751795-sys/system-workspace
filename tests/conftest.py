"""Centralized test path setup.

Adds scripts/ and package src/ directories to sys.path so individual test
files don't need their own sys.path.insert calls.

CI sets PYTHONPATH to the same package paths — this conftest replicates
that for local development.

P0-2: optional operator-tree hash guard — when Data/ or Output/ exist,
snapshot lightweight fingerprints before the session and assert unchanged
after (tests must not mutate operator state).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_paths_to_add = [
    str(_ROOT / "scripts"),
    str(_ROOT / "packages" / "framework"),
    str(_ROOT / "packages" / "framework" / "src"),
    str(_ROOT / "packages" / "harvester" / "src"),
    str(_ROOT / "packages" / "learning_hub" / "src"),
    # workbench/src last so it wins path priority (richer nlp/workbench packages
    # must not be shadowed by framework's slimmer nlp/event_translator package).
    str(_ROOT / "packages" / "workbench" / "src"),
]

for _p in _paths_to_add:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _dir_fingerprint(path: Path, *, limit: int = 200) -> str:
    """Cheap fingerprint: sorted relative paths + sizes (not full content)."""
    if not path.exists():
        return "missing"
    rows: list[str] = []
    count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            if name.startswith("."):
                continue
            fp = Path(root) / name
            try:
                rel = fp.relative_to(path).as_posix()
                size = fp.stat().st_size
            except OSError:
                continue
            rows.append(f"{rel}:{size}")
            count += 1
            if count >= limit:
                break
        if count >= limit:
            break
    digest = hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()
    return f"{count}:{digest}"


@pytest.fixture(scope="session", autouse=True)
def _operator_tree_hash_guard():
    """Fail the session if tests mutate pre-existing operator Data/ or Output/."""
    if os.environ.get("SYSTEM_TEST_SKIP_OPERATOR_HASH_GUARD") == "1":
        yield
        return
    targets = [_ROOT / "Data", _ROOT / "Output"]
    before = {str(p): _dir_fingerprint(p) for p in targets if p.exists()}
    yield
    drifted = []
    for key, fingerprint in before.items():
        path = Path(key)
        if not path.exists():
            drifted.append(f"{key} (deleted)")
            continue
        if _dir_fingerprint(path) != fingerprint:
            drifted.append(key)
    if drifted:
        pytest.fail(
            "Operator Data/Output fingerprint changed during tests "
            f"(P0-2 isolation violation): {drifted}"
        )
