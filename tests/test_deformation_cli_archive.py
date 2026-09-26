"""Harness deformation CLI is a read-only ARCHIVED_FALSIFIED archive browser."""
from __future__ import annotations

from pathlib import Path

from tests._harness_tools import harness_tools_owner

with harness_tools_owner():
    from entrypoints.deformation_cli import HELP, main
    from tools.deformation_tools import _h_run_snapshot


def test_deformation_help_first_line_is_archived_falsified() -> None:
    first_line = HELP.splitlines()[0]
    assert "ARCHIVED_FALSIFIED" in first_line
    assert "inspect archived v1 snapshots" in first_line.lower() or "archived v1" in first_line.lower()


def test_deformation_help_has_no_run_fetch_analyze() -> None:
    lowered = HELP.lower()
    assert "list-snapshots" in lowered
    assert "inspect-snapshot" in lowered
    assert "never run, fetch, or analyze" in lowered


def test_system_deformation_help_prints_archived_falsified(capsys) -> None:
    with harness_tools_owner():
        rc = main(["--help"])
    captured = capsys.readouterr()
    first_line = captured.out.splitlines()[0]
    assert rc == 0
    assert "ARCHIVED_FALSIFIED" in first_line


def test_run_snapshot_tool_is_permanently_denied() -> None:
    with harness_tools_owner():
        result = _h_run_snapshot({}, dry_run=False)
    assert result.ok is False
    assert result.tool_id == "deformation.run_snapshot"
    assert "ARCHIVED_FALSIFIED" in result.summary
    assert any("never run" in err.lower() for err in result.errors)


def test_harness_run_snapshot_mentions_are_denials() -> None:
    harness = Path(__file__).resolve().parents[1] / "packages" / "workbench" / "agents" / "harness"
    denial_tokens = ("denied", "deny", "permanently", "archived_falsified", "never run")
    violations: list[str] = []
    for path in harness.rglob("*"):
        if path.suffix not in {".py", ".md", ".yaml", ".json"}:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "run_snapshot" not in text:
            continue
        lowered = text.lower()
        if not any(token in lowered for token in denial_tokens):
            rel = path.relative_to(harness).as_posix()
            violations.append(rel)
    assert violations == [], "non-denial run_snapshot mentions:\n" + "\n".join(violations)
