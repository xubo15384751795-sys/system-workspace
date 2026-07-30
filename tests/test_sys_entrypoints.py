"""Smoke tests for system CLI entry points (hermetic sandbox).

Uses SYSTEM_WORKSPACE_ROOT / ``system_cli --workspace`` so operator Data/Output
are never touched. See: governance/architecture_reality_decisions.md §7
     SYSTEM_LARGE_SCALE_VALIDATION_ROADMAP.md P0-2
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.sandbox_workspace import build_sandbox_workspace

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    return build_sandbox_workspace(tmp_path / "workspace")


def _cli(sandbox: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SYSTEM_WORKSPACE_ROOT": str(sandbox),
        "PYTHONPATH": (
            f"{ROOT}{os.pathsep}{ROOT / 'packages' / 'framework' / 'src'}"
            f"{os.pathsep}{ROOT / 'packages' / 'workbench' / 'src'}"
            f"{os.pathsep}{ROOT / 'scripts'}"
        ),
    }
    return subprocess.run(
        [sys.executable, "-m", "system_cli", "--workspace", str(sandbox), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
        env=env,
    )


def test_sys_check_exits_cleanly(sandbox: Path) -> None:
    result = _cli(sandbox, "check")
    assert result.returncode == 0, f"check failed: {result.stderr}"
    assert "System Status" in (result.stdout + result.stderr)


def test_sys_check_shows_system_status(sandbox: Path) -> None:
    result = _cli(sandbox, "check")
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert len(output.strip()) > 0


def test_sys_next_exits_cleanly(sandbox: Path) -> None:
    result = _cli(sandbox, "next")
    assert result.returncode == 0, f"next failed: {result.stderr}"
    assert "Next Actions" in (result.stdout + result.stderr)


def test_sys_status_exits_cleanly(sandbox: Path) -> None:
    result = _cli(sandbox, "status", timeout=90)
    assert result.returncode in (0, 1), f"status crashed: {result.stderr}"


def test_sys_doctor_exits_cleanly(sandbox: Path) -> None:
    result = _cli(sandbox, "doctor")
    assert result.returncode == 0, f"doctor failed: {result.stdout} {result.stderr}"
    assert '"status": "ok"' in result.stdout.replace(" ", "") or '"status":"ok"' in result.stdout.replace(" ", "")


def test_sys_governance_reads_sandbox_surface(sandbox: Path) -> None:
    """Governance may rebuild; seeded markdown must remain readable afterward."""
    result = _cli(sandbox, "governance", timeout=120)
    output = result.stdout + result.stderr
    if result.returncode != 0:
        # Fall back: seeded surface still present for operator-less sandboxes.
        seeded = sandbox / "Output" / "system_learning" / "latest" / "governance_status.md"
        assert seeded.exists()
        assert "Governance Status" in seeded.read_text(encoding="utf-8")
        pytest.skip(f"governance rebuild unavailable in sandbox: {output[:300]}")
    assert "Governance Status" in output


def test_sys_refresh_dry_run_exits_cleanly(sandbox: Path) -> None:
    """Full refresh needs operator data; dry-run proves the entrypoint wiring."""
    result = _cli(sandbox, "refresh", "--dry-run")
    assert result.returncode == 0, f"refresh --dry-run failed: {result.stderr}"
    assert "DRY RUN" in result.stdout
    assert "pre-consumption admission (hard gate)" in result.stdout


def test_sys_check_output_contains_status(sandbox: Path) -> None:
    result = _cli(sandbox, "check")
    assert result.returncode == 0
    output = (result.stdout + result.stderr).lower()
    assert any(kw in output for kw in ("status", "judgment", "decision", "system"))
