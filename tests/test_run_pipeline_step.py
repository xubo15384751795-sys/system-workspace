"""Tests for single-step pipeline runner CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = ROOT / "packages" / "workbench" / "agents" / "harness"


def test_list_registry_steps_includes_judgment_layer() -> None:
    from _pipeline_runner import list_registry_steps

    steps = list_registry_steps()
    ids = {step["step_id"] for step in steps}
    assert "judgment_layer" in ids
    assert "evidence_grade_report" in ids


def test_run_pipeline_step_list_cli() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_pipeline_step.py"), "list", "--json"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["count"] >= 10


def test_run_pipeline_step_dry_run() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_pipeline_step.py"),
            "run",
            "--dry-run",
            "evidence_grade_report",
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["dry_run"] is True
    assert payload["step_id"] == "evidence_grade_report"


def test_system_run_list_via_harness() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(HARNESS_ROOT / "entrypoints" / "system.py"),
            "run",
            "list",
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["count"] >= 10
