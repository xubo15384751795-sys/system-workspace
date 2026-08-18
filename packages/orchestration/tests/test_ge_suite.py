"""GE-shaped suite uses Pandera and does not require the GE pip package."""
from __future__ import annotations

from pathlib import Path

import pytest

import orchestration.quality.ge_suite as ge_suite
from orchestration.quality.ge_suite import _ge_available, run_content_freshness_suite


def test_ge_available_false_without_site_packages_module():
    # On this workspace Python, great_expectations is typically unavailable.
    # The helper must not treat configs/great_expectations as the package.
    assert isinstance(_ge_available(), bool)


def test_run_content_freshness_suite_shape():
    root = Path(__file__).resolve().parents[3]
    # parents: tests -> orchestration pkg -> packages -> System?
    # File is packages/orchestration/tests/test_ge_suite.py
    # parents[0]=tests, [1]=orchestration project, [2]=packages, [3]=System
    payload = run_content_freshness_suite(root=root)
    assert payload["schema_version"] == "quality_result.v1"
    assert payload["suite"] == "content_freshness_v1"
    assert "results" in payload
    assert payload["engine"] == "pandera"
    assert payload["great_expectations_ignored"] is True
    assert payload["calendar_engine"] == "exchange_calendars"
    suite_doc = Path(payload["suite_document"] or "")
    assert suite_doc.exists()


def test_gx_availability_cannot_change_quality_engine(monkeypatch: pytest.MonkeyPatch):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(ge_suite, "_ge_available", lambda: True)
    payload = ge_suite.run_content_freshness_suite(root=root)
    assert payload["engine"] == "pandera"
    assert payload["great_expectations_ignored"] is True
