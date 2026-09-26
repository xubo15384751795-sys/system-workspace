"""Paper world-model sync freshness heartbeat."""
from __future__ import annotations

import json
from pathlib import Path

from harvester.operators.sync_paper_world_model import SCAN_DIRS, run_sync


def test_unchanged_paper_refreshes_synced_at_heartbeat(tmp_path: Path) -> None:
    paper = tmp_path / "Paper"
    for subdir, _category, _extractor in SCAN_DIRS:
        (paper / subdir).mkdir(parents=True, exist_ok=True)
    case = paper / "01_Cases" / "Example.md"
    case.write_text(
        "---\ntype: case\ncase_type: structural\nstatus: candidate\n"
        "review_status: needs_review\nmain_entity: X\ncountry: US\nsector: tech\n"
        "trade_relevance: medium\n---\n\nbody\n",
        encoding="utf-8",
    )

    out = tmp_path / "wm"
    report = tmp_path / "report"
    first = run_sync(paper_dir=paper, output_dir=out, report_dir=report, quiet_on_success=True)
    assert first.get("skipped") is not True
    synced_1 = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["synced_at"]

    second = run_sync(paper_dir=paper, output_dir=out, report_dir=report, quiet_on_success=True)
    assert second.get("skipped") is True
    assert second.get("reason") == "paper_unchanged"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synced_at"] >= synced_1
    assert manifest.get("freshness_check") == "paper_unchanged_heartbeat"
    assert second["synced_at"] == manifest["synced_at"]
