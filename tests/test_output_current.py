"""Current-output contract tests (hermetic sandbox + fixtures).

Does not refresh the operator Output/current tree. Structural assertions use
committed fixtures; refresh wiring is covered by --dry-run only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts._runtime_status_contract import judgment_decision_values
from tests.helpers.sandbox_workspace import build_sandbox_workspace

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "current_chain"


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    return build_sandbox_workspace(tmp_path / "workspace")


def test_output_current_fixture_surfaces_exist(sandbox: Path) -> None:
    current = sandbox / "Output" / "current"
    judgment = sandbox / "Output" / "judgment"
    assert (current / "framework_output.json").exists()
    assert (current / "00_READ_ME_FIRST.md").exists()
    assert (judgment / "latest.json").exists()
    assert (judgment / "latest.md").exists()
    assert (judgment / "promotion_gate.json").exists()
    assert (judgment / "promotion_gate.md").exists()


def test_readme_points_to_judgment(sandbox: Path) -> None:
    text = (sandbox / "Output" / "current" / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    assert "System Status" in text
    assert "Judgment:" in text
    assert "Trade Decision:" in text
    assert "Risk Gate:" in text


def test_readme_contains_system_status(sandbox: Path) -> None:
    text = (sandbox / "Output" / "current" / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    assert "System Status" in text
    assert "Judgment:" in text


def test_readme_forbidden_language_section_present(sandbox: Path) -> None:
    text = (sandbox / "Output" / "current" / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    assert "## Forbidden Language" in text
    gate = json.loads(
        (sandbox / "Output" / "judgment" / "promotion_gate.json").read_text(encoding="utf-8")
    )
    for term in gate.get("forbidden_language", []):
        assert term.lower() in text.lower()


def test_judgment_card_structure(sandbox: Path) -> None:
    judgment = json.loads(
        (sandbox / "Output" / "judgment" / "latest.json").read_text(encoding="utf-8")
    )
    assert "decision" in judgment
    assert "confidence" in judgment
    assert "claim_ceiling" in judgment
    assert judgment["decision"] in judgment_decision_values(include_legacy=True)


def test_promotion_gate_blocks_weak_signals(sandbox: Path) -> None:
    gate = json.loads(
        (sandbox / "Output" / "judgment" / "promotion_gate.json").read_text(encoding="utf-8")
    )
    assert gate.get("status") == "BLOCKED"
    assert gate.get("blocked_gates")


def test_refresh_dry_run_does_not_require_operator_data() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "refresh_output_current.py"), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(ROOT),
        env={
            **os.environ,
            "PYTHONPATH": (
                f"{ROOT}{os.pathsep}{ROOT / 'packages' / 'workbench' / 'src'}"
                f"{os.pathsep}{ROOT / 'packages' / 'orchestration'}"
                f"{os.pathsep}{ROOT / 'scripts'}"
            ),
        },
    )
    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
