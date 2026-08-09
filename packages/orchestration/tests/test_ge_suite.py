"""GE-shaped suite uses Pandera and does not require the GE pip package."""
from __future__ import annotations

from pathlib import Path

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
    assert payload["suite"] == "content_freshness_v1"
    assert "results" in payload
    assert payload["engine"] in {"pandera", "great_expectations+pandera"}
    suite_doc = Path(payload["suite_document"] or "")
    assert suite_doc.exists()
