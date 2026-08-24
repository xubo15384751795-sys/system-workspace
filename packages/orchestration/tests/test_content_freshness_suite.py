"""Content-clock quality suite shape and engine invariance."""
from __future__ import annotations

from pathlib import Path

from orchestration.quality.content_freshness_suite import (
    run_content_freshness_quality_suite,
)


def test_run_content_freshness_quality_suite_shape():
    root = Path(__file__).resolve().parents[3]
    payload = run_content_freshness_quality_suite(root=root)
    assert payload["schema_version"] == "quality_result.v1"
    assert payload["suite"] == "content_freshness_v1"
    assert "results" in payload
    assert payload["engine"] == "pandera"
    assert "great_expectations_ignored" not in payload
    assert payload["calendar_engine"] == "exchange_calendars"
    suite_doc = Path(payload["suite_document"] or "")
    assert suite_doc.exists()
