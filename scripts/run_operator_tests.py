#!/usr/bin/env python3
"""Run operator tests in a temporary, isolated workspace.

The operator suite is intentionally stateful: several tests refresh current
artifacts or build indexes.  Running it from the authoring checkout would
make the ignored ``Data/`` and ``Output/`` trees part of the test side
effects.  This entrypoint therefore requires an explicit opt-in, clones the
whole workspace into a temporary directory, and runs pytest from that clone.

On macOS, ``cp -cR`` gives the seed Data/Output trees copy-on-write semantics;
other platforms use an ordinary isolated copy.  The source checkout's
Data/Output fingerprints are checked before and after the child process in
both cases.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT_SECONDS = 90 * 60
REQUIRED_DURATION_ARGUMENT = "--durations=25"
_COPY_EXCLUDES = frozenset(
    {
        ".git",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "Data",
        "Output",
    }
)


def _tree_fingerprint(path: Path) -> str:
    """Hash every file byte and symlink target below *path*."""
    if not path.exists():
        return "missing"

    rows: list[str] = []
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = sorted(dirs)
        files[:] = sorted(files)
        root_path = Path(root)
        for name in dirs + files:
            candidate = root_path / name
            relative = candidate.relative_to(path).as_posix()
            if candidate.is_symlink():
                rows.append(f"L:{relative}:{os.readlink(candidate)}")
                continue
            if not candidate.is_file():
                continue
            digest = hashlib.sha256()
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            rows.append(f"F:{relative}:{digest.hexdigest()}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _clone_tree(source: Path, target: Path) -> str:
    """Clone a directory into an existing empty target and return the mode."""
    target.mkdir(parents=True, exist_ok=True)
    cp = shutil.which("cp")
    if sys.platform == "darwin" and cp:
        result = subprocess.run(
            [cp, "-cR", str(source / "."), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return "copy_on_write_clone"
        shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

    shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
    return "isolated_copy"


def _copy_workspace(source: Path, target: Path) -> dict[str, str]:
    """Copy source code and clone operator trees into *target*."""
    source = source.resolve()
    target = target.resolve()

    def ignore(_path: str, names: list[str]) -> set[str]:
        return set(names).intersection(_COPY_EXCLUDES)

    shutil.copytree(source, target, symlinks=True, ignore=ignore)
    modes: dict[str, str] = {}
    for name in ("Data", "Output"):
        source_tree = source / name
        if source_tree.exists():
            modes[name] = _clone_tree(source_tree, target / name)
    return modes


def _operator_environment(workspace: Path) -> dict[str, str]:
    env = dict(os.environ)
    # A caller's PYTHONPATH may point back to the authoring checkout.  The
    # copied pyproject.toml and tests/conftest.py provide the target paths.
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "SYSTEM_OPERATOR_WORKSPACE": str(workspace),
            "SYSTEM_OPERATOR_ISOLATED": "1",
            "SYSTEM_WORKSPACE_ROOT": str(workspace),
            "SYSTEM_ROOT": str(workspace),
        }
    )
    return env


def _pytest_command(py: str, pytest_args: list[str]) -> list[str]:
    """Build the operator command with mandatory slow-test evidence."""
    if any(
        argument == "--durations" or argument.startswith("--durations=")
        for argument in pytest_args
    ):
        raise ValueError(
            f"operator runner owns {REQUIRED_DURATION_ARGUMENT}; do not override it"
        )
    return [
        py,
        "-m",
        "pytest",
        "tests",
        "-q",
        "-m",
        "operator",
        "--maxfail=1",
        REQUIRED_DURATION_ARGUMENT,
        *pytest_args,
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run -m operator in a temporary isolated workspace."
    )
    parser.add_argument(
        "--allow-operator-workspace",
        action="store_true",
        help="explicitly authorize the stateful operator test run",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=_ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "hard timeout for the isolated operator pytest process "
            f"(default: {DEFAULT_TIMEOUT_SECONDS}s)"
        ),
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="optional arguments passed to pytest after the operator selection",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.allow_operator_workspace:
        print(
            "operator tests require explicit --allow-operator-workspace; "
            "the authoring checkout is never used directly",
            file=sys.stderr,
        )
        return 2
    if args.timeout_seconds <= 0:
        print("operator timeout must be positive", file=sys.stderr)
        return 2

    source = args.source_root.resolve()
    if not (source / "pyproject.toml").is_file() or not (source / "tests").is_dir():
        print(f"invalid System workspace: {source}", file=sys.stderr)
        return 2

    original_fingerprints = {
        name: _tree_fingerprint(source / name) for name in ("Data", "Output")
    }
    pytest_args = list(args.pytest_args)
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]

    with tempfile.TemporaryDirectory(prefix="system-operator-") as temp_dir:
        workspace = Path(temp_dir) / "System"
        modes = _copy_workspace(source, workspace)
        print(
            "[operator] isolated workspace="
            f"{workspace} Data={modes.get('Data', 'missing')} "
            f"Output={modes.get('Output', 'missing')}",
            flush=True,
        )
        try:
            command = _pytest_command(sys.executable, pytest_args)
        except ValueError as exc:
            print(f"operator runner configuration error: {exc}", file=sys.stderr)
            return 2
        try:
            child = subprocess.run(
                command,
                cwd=workspace,
                env=_operator_environment(workspace),
                check=False,
                timeout=args.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            print(
                "operator pytest timed out after "
                f"{args.timeout_seconds}s; isolated workspace was discarded",
                file=sys.stderr,
            )
            return 124

    current_fingerprints = {
        name: _tree_fingerprint(source / name) for name in ("Data", "Output")
    }
    if current_fingerprints != original_fingerprints:
        print(
            "operator isolation violation: authoring checkout Data/Output "
            "fingerprint changed",
            file=sys.stderr,
        )
        return 3
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
