"""Automation helpers — incremental sync and feedback export dedupe."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "archive" / "governance_cut_2026_06_20"))

import export_feedback_to_paper as efp
import sync_paper_world_model as spwm


def test_incremental_sync_skips_when_unchanged(tmp_path: Path) -> None:
    paper_dir = tmp_path / "Paper"
    output_dir = tmp_path / "out"
    report_dir = tmp_path / "report"

    case = paper_dir / "01_Cases" / "sample.md"
    case.parent.mkdir(parents=True)
    case.write_text(
        """---
type: case
review_status: approved
---
# Sample
""",
        encoding="utf-8",
    )

    first = spwm.run_sync(
        paper_dir=paper_dir,
        output_dir=output_dir,
        report_dir=report_dir,
        quiet_on_success=True,
    )
    assert first.get("cases") == 1

    second = spwm.run_sync(
        paper_dir=paper_dir,
        output_dir=output_dir,
        report_dir=report_dir,
        quiet_on_success=True,
    )
    assert second.get("skipped") is True
    assert second.get("reason") == "paper_unchanged"


def test_export_feedback_skips_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paper_dir = tmp_path / "Paper"
    paper_dir.mkdir()
    log = ROOT / "caselab_context" / "feedback_log.jsonl"
    state = tmp_path / "state.json"
    monkeypatch.setattr(efp, "STATE_PATH", state)
    monkeypatch.setattr(efp, "OUTPUT_REPORT", tmp_path / "report.json")
    monkeypatch.setattr(efp, "paper_root", lambda: paper_dir)

    row = {
        "feedback_id": "ctx-test-001",
        "review_status": "needs_review",
        "timestamp": "2026-06-18T00:00:00Z",
        "input": {"actor": "A", "verb": "b", "object": "c", "regime": {}},
        "contextual_meaning": {},
        "matched_rules": [],
    }
    def fake_read(path: Path) -> list[dict]:
        if "preference" in str(path):
            return []
        return [row]

    monkeypatch.setattr(efp, "_read_jsonl", fake_read)

    first = efp.export_feedback(paper_dir)
    assert first["exported_count"] == 1

    second = efp.export_feedback(paper_dir)
    assert second["exported_count"] == 0
    assert second["skipped_unchanged_count"] == 1

    third = efp.export_feedback(paper_dir, force=True)
    assert third["exported_count"] == 1


def test_lint_paper_frontmatter_detects_missing_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lint_paper_frontmatter import lint_paper

    paper_dir = tmp_path / "Paper"
    bad = paper_dir / "03_Mechanisms" / "bad.md"
    bad.parent.mkdir(parents=True)
    bad.write_text("---\ntype: mechanism\nreview_status: approved\n---\n", encoding="utf-8")
    monkeypatch.chdir(ROOT)
    errors = lint_paper(paper_dir)
    assert errors == []

    worse = paper_dir / "03_Mechanisms" / "worse.md"
    worse.write_text("# no frontmatter\n", encoding="utf-8")
    errors = lint_paper(paper_dir)
    assert any(e["file"].endswith("worse.md") for e in errors)
