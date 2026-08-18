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


def _full_tree_fingerprint(path: Path) -> str:
    """Hash every operator-tree byte and symlink target."""
    if not path.exists():
        return "missing"
    rows: list[str] = []
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = sorted(dirs)
        files[:] = sorted(files)
        root_path = Path(root)
        for name in dirs:
            candidate = root_path / name
            if candidate.is_symlink():
                rows.append(
                    f"L:{candidate.relative_to(path).as_posix()}:{os.readlink(candidate)}"
                )
        for name in files:
            candidate = root_path / name
            relative = candidate.relative_to(path).as_posix()
            if candidate.is_symlink():
                rows.append(f"L:{relative}:{os.readlink(candidate)}")
                continue
            digest = hashlib.sha256()
            try:
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                rows.append(f"F:{relative}:{digest.hexdigest()}")
            except OSError:
                rows.append(f"F:{relative}:UNREADABLE")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


@pytest.fixture(scope="session", autouse=True)
def _hermetic_workspace_guard():
    """Always-on guard: fail if a hermetic test session creates repo-root Data/ or Output/.

    Snapshots whether ``Data`` and ``Output`` exist at the repo root before the
    session.  If either was absent and appeared after the session, the session
    failed hermeticity.  This catches tests that write to real operator state
    instead of ``tmp_path``.

    When the dirs already exist (operator workspace), this guard defers to the
    opt-in ``_operator_tree_hash_guard`` below - it does not duplicate that
    check.
    """
    data_path = _ROOT / "Data"
    output_path = _ROOT / "Output"
    data_existed = data_path.exists()
    output_existed = output_path.exists()
    yield
    violations = []
    if not data_existed and data_path.exists():
        violations.append(str(data_path))
    if not output_existed and output_path.exists():
        violations.append(str(output_path))
    if violations:
        pytest.fail(
            "Hermetic violation: test session created repo-root "
            f"directory(s) that did not exist before: {violations}"
        )


@pytest.fixture(scope="session", autouse=True)
def _operator_tree_hash_guard(request: pytest.FixtureRequest):
    """Require isolation for operator tests and guard direct mixed sessions.

    The supported operator entrypoint sets ``SYSTEM_OPERATOR_ISOLATED=1`` and
    points ``SYSTEM_OPERATOR_WORKSPACE`` at the copied checkout.  Running
    ``pytest -m operator`` directly therefore fails before any stateful test
    starts.  Mixed non-isolated sessions may still opt into the complete hash
    guard with ``SYSTEM_TEST_OPERATOR_HASH_GUARD=1``.
    """
    selected_operator = any(
        item.get_closest_marker("operator") is not None
        for item in request.session.items
    )
    isolated = os.environ.get("SYSTEM_OPERATOR_ISOLATED") == "1"
    if selected_operator:
        workspace = os.environ.get("SYSTEM_OPERATOR_WORKSPACE", "").strip()
        if not isolated or not workspace:
            pytest.fail(
                "operator tests require scripts/run_operator_tests.py "
                "--allow-operator-workspace"
            )
        if Path(workspace).resolve() != _ROOT.resolve():
            pytest.fail(
                "SYSTEM_OPERATOR_WORKSPACE must equal the pytest workspace "
                f"({workspace!r} != {str(_ROOT)!r})"
            )
        # The runner fingerprints the authoring checkout.  The operator copy
        # is intentionally allowed to update its own Data/Output surfaces.
        yield
        return

    explicitly_enabled = os.environ.get("SYSTEM_TEST_OPERATOR_HASH_GUARD") == "1"
    if not selected_operator and not explicitly_enabled:
        yield
        return
    targets = [_ROOT / "Data", _ROOT / "Output"]
    before = {str(p): _full_tree_fingerprint(p) for p in targets if p.exists()}
    yield
    drifted = []
    for key, fingerprint in before.items():
        path = Path(key)
        if not path.exists():
            drifted.append(f"{key} (deleted)")
            continue
        if _full_tree_fingerprint(path) != fingerprint:
            drifted.append(key)
    if drifted:
        pytest.fail(
            "Operator Data/Output fingerprint changed during tests "
            f"(P0-2 isolation violation): {drifted}"
        )
