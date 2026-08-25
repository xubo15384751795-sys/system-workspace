"""Behavioral tests for the scheduler-to-Dagster fail-closed boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _fake_python_without_dagster(tmp_path: Path) -> Path:
    launcher = tmp_path / "python-without-dagster"
    launcher.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then exit 1; fi\n"
        f"exec {sys.executable!s} \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def _run_orchestrate(fake_python: Path, *, legacy: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "SYSTEM_ROOT": str(ROOT),
            "PYTHON": str(fake_python),
            "PYTHONPATH": f"{ROOT}:{ROOT / 'packages/orchestration'}",
        }
    )
    if legacy:
        env["SYSTEM_USE_LEGACY_DAILY_RUN"] = "1"
    else:
        env.pop("SYSTEM_USE_LEGACY_DAILY_RUN", None)
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "orchestrate.sh"), "daily", "--dry-run"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_default_path_fails_closed_when_dagster_is_unavailable(tmp_path: Path) -> None:
    result = _run_orchestrate(_fake_python_without_dagster(tmp_path))
    assert result.returncode == 78
    assert "default path is fail-closed" in result.stderr


def test_legacy_path_requires_explicit_audited_flag(tmp_path: Path) -> None:
    result = _run_orchestrate(_fake_python_without_dagster(tmp_path), legacy=True)
    assert result.returncode == 0
    assert "DRY RUN - would execute:" in result.stdout


def test_definitions_load_when_generation_mode_has_no_directory() -> None:
    pytest.importorskip("dagster")
    env = os.environ.copy()
    env.update(
        {
            "SYSTEM_ROOT": str(ROOT),
            "PYTHONPATH": f"{ROOT}:{ROOT / 'packages/orchestration'}",
            "SYSTEM_GENERATION_MODE": "1",
        }
    )
    env.pop("SYSTEM_GENERATION_DIR", None)
    env.pop("SYSTEM_USE_LEGACY_DAILY_RUN", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from orchestration.definitions import daily_job, defs",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "generation mode requires SYSTEM_GENERATION_DIR" not in result.stderr


def test_default_dry_run_loads_when_generation_mode_has_no_directory() -> None:
    pytest.importorskip("dagster")
    env = os.environ.copy()
    env.update(
        {
            "SYSTEM_ROOT": str(ROOT),
            "PYTHON": sys.executable,
            "PYTHONPATH": f"{ROOT}:{ROOT / 'packages/orchestration'}",
            "SYSTEM_GENERATION_MODE": "1",
        }
    )
    env.pop("SYSTEM_GENERATION_DIR", None)
    env.pop("SYSTEM_USE_LEGACY_DAILY_RUN", None)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "orchestrate.sh"), "daily", "--dry-run"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "DRY RUN - would execute:" in result.stdout
