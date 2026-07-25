from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from system_learning.cli import main
from system_learning.variation import build_variation_health, count_current_entries


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_comments_and_rules_do_not_count_as_hypotheses(tmp_path: Path) -> None:
    inbox = tmp_path / "hypotheses_inbox.md"
    inbox.write_text(
        "# Inbox\nprose\n<!-- Add raw one-line hypotheses below. "
        "Comments and blank lines do not count. -->\n"
        "<!-- comment -->\nraw idea\n",
        encoding="utf-8",
    )
    assert count_current_entries(inbox) == 1


def test_untracked_seed_entries_make_inlet_healthy(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    (tmp_path / "hypotheses_inbox.md").write_text(
        "idea one\nidea two\n",
        encoding="utf-8",
    )
    report = build_variation_health(tmp_path)
    assert report["status"] == "PASS"
    assert report["recent_added_line_count"] == 2
    assert report["authority"] == "none"


def test_zero_inflow_is_a_failing_exception_only_cli(tmp_path: Path, capsys) -> None:
    _git(tmp_path, "init")
    (tmp_path / "hypotheses_inbox.md").write_text("", encoding="utf-8")
    exit_code = main(["variation-health", "--system-root", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "zero hypothesis inflow" in captured.err
    assert (tmp_path / "Output/system_learning/latest/hypothesis_inflow.json").is_file()


def test_old_uncommitted_inbox_does_not_mask_monthly_zero(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    inbox = tmp_path / "hypotheses_inbox.md"
    inbox.write_text("old idea\n", encoding="utf-8")
    old = time.time() - 40 * 24 * 3600
    os.utime(inbox, (old, old))
    report = build_variation_health(tmp_path, days=30)
    assert report["status"] == "DEVIATION"
    assert report["recent_added_line_count"] == 0
