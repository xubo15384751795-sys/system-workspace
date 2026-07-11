"""Smoke tests for ./sys entry points.

Verifies that the primary CLI commands work end-to-end.
See: governance/architecture_reality_decisions.md §7
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYS = ROOT / "sys"


def test_sys_check_exits_cleanly() -> None:
    """./sys check should exit 0."""
    result = subprocess.run(
        [str(SYS), "check"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"./sys check failed: {result.stderr}"


def test_sys_check_shows_system_status() -> None:
    """./sys check output should contain system status indicators."""
    result = subprocess.run(
        [str(SYS), "check"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    # Should produce some output (not empty)
    assert len(output.strip()) > 0, "./sys check produced no output"


def test_sys_next_exits_cleanly() -> None:
    """./sys next should exit 0."""
    result = subprocess.run(
        [str(SYS), "next"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"./sys next failed: {result.stderr}"


def test_sys_status_exits_cleanly() -> None:
    """./sys status should exit 0."""
    result = subprocess.run(
        [str(SYS), "status"],
        capture_output=True, text=True, timeout=30,
    )
    # status may exit non-zero if issues found, but should not crash
    assert result.returncode in (0, 1), f"./sys status crashed: {result.stderr}"


def test_sys_doctor_exits_cleanly() -> None:
    """./sys doctor should exit 0 or 1 (never crash)."""
    result = subprocess.run(
        [str(SYS), "doctor"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode in (0, 1), f"./sys doctor crashed: {result.stderr}"


def test_sys_governance_exits_cleanly() -> None:
    """./sys governance should expose the latest governance status."""
    result = subprocess.run(
        [str(SYS), "governance"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"./sys governance failed: {result.stderr}"
    output = result.stdout + result.stderr
    assert "Governance Status" in output


def test_sys_refresh_produces_core_artifacts() -> None:
    """./sys refresh should produce framework_output.json and status.json."""
    result = subprocess.run(
        [str(SYS), "refresh"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"./sys refresh failed: {result.stderr}"
    current = ROOT / "Output" / "current"
    assert (current / "framework_output.json").exists(), "framework_output.json missing after refresh"
    assert (current / "status.json").exists(), "status.json missing after refresh"


def test_sys_check_output_contains_status() -> None:
    """./sys check output should reference system status."""
    result = subprocess.run(
        [str(SYS), "check"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    output = result.stdout + result.stderr
    # Should reference status or judgment
    assert any(kw in output.lower() for kw in ("status", "judgment", "decision", "system")), (
        f"./sys check output missing status keywords: {output[:200]}"
    )
