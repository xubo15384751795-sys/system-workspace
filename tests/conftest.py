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
    str(_ROOT / "packages" / "orchestration"),
    str(_ROOT / "packages" / "framework"),
    str(_ROOT / "packages" / "framework" / "src"),
    str(_ROOT / "packages" / "harvester" / "src"),
    str(_ROOT / "packages" / "learning_hub" / "src"),
    str(_ROOT / "packages" / "workbench" / "src"),
]

for _p in _paths_to_add:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Structural NLP lives under workbench as top-level ``nlp``. Framework's former
# ``src.nlp`` package was renamed to ``src.framework_nlp``; still force
# workbench/src to the front in case PYTHONPATH already contained framework/src.
_WORKBENCH_SRC = str(_ROOT / "packages" / "workbench" / "src")
if _WORKBENCH_SRC in sys.path:
    sys.path.remove(_WORKBENCH_SRC)
sys.path.insert(0, _WORKBENCH_SRC)
_stale = [
    name
    for name, mod in list(sys.modules.items())
    if name == "nlp" or name.startswith("nlp.")
]
for name in _stale:
    mod = sys.modules.get(name)
    origin = getattr(mod, "__file__", "") or ""
    if "framework" in origin.replace("\\", "/"):
        del sys.modules[name]


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
    """Opt-in guard: fail if tests mutate pre-existing operator Data/ or Output/.

    Enable with SYSTEM_TEST_OPERATOR_HASH_GUARD=1 on an initialized operator
    workspace. Disabled by default so clean CI / merge-gate suites that still
    write under Data/ during non-hermetic tests are not blocked (P0-2 follow-up).
    """
    if os.environ.get("SYSTEM_TEST_OPERATOR_HASH_GUARD") != "1":
        yield
        return
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
