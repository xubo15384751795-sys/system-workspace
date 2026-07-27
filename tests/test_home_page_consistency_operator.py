"""Operator-bound home-page / freshness monitor path existence checks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"


def test_freshness_monitored_paths_exist() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from freshness_validator import CONTENT_FRESHNESS

    missing = []
    for name, cfg in CONTENT_FRESHNESS.items():
        p = ROOT / cfg["path"]
        if not p.exists():
            missing.append(f"{name}: {cfg['path']}")

    artifact_paths = {
        "readme_first": CURRENT / "00_READ_ME_FIRST.md",
        "signal_card": CURRENT / "signal_card.json",
        "work_brief": CURRENT / "work_brief.json",
        "learning_summary": ROOT
        / "Output"
        / "system_learning"
        / "latest"
        / "comprehensive_summary.json",
        "system_index": ROOT / "Data" / "system_index" / "latest.json",
        "trade_decision": ROOT / "Output" / "trade_decision" / "latest.json",
    }
    for name, p in artifact_paths.items():
        if not p.exists():
            missing.append(f"{name}: {p.relative_to(ROOT)}")

    assert not missing, (
        "freshness_validator monitors paths that do not exist: " f"{missing}"
    )


def test_freshness_report_no_false_missing() -> None:
    report_path = ROOT / "Output" / "quality" / "freshness_report.json"
    if not report_path.exists():
        pytest.skip("freshness_report.json not found")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    missing = report.get("missing_artifacts", [])
    path_map = {
        "readme_first": CURRENT / "00_READ_ME_FIRST.md",
        "signal_card": CURRENT / "signal_card.json",
        "signal_consensus": CURRENT / "signal_consensus.json",
        "work_brief": CURRENT / "work_brief.json",
        "learning_summary": ROOT
        / "Output"
        / "system_learning"
        / "latest"
        / "comprehensive_summary.json",
    }
    false_missing = [name for name in missing if name in path_map and path_map[name].exists()]
    assert not false_missing, (
        f"freshness report lists MISSING for files that exist: {false_missing}."
    )
