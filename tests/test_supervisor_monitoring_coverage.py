from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_supervisor_check as supervisor  # noqa: E402


def test_supervisor_surfaces_monitoring_blind_spots(tmp_path: Path, monkeypatch) -> None:
    report_path = tmp_path / "monitoring_coverage.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "WARN",
                "summary": {
                    "weekly_stale_or_missing_count": 2,
                    "weekly_no_content_clock_count": 1,
                },
                "monitoring_blind_spots": [
                    {"family": "Output/unowned", "count": 4, "examples": ["Output/unowned/a.json"]}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor, "MONITORING_COVERAGE_PATH", report_path)

    result = supervisor._check_monitoring_coverage()

    assert result["status"] == "WARN"
    assert result["summary"]["weekly_stale_or_missing_count"] == 2
    assert result["blind_spot_families"][0]["family"] == "Output/unowned"
