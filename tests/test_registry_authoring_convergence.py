"""Parity and authority tests for the split pipeline authoring sources."""
from __future__ import annotations

from pathlib import Path

from tools.audit.registry_authoring_convergence import build_report

ROOT = Path(__file__).resolve().parents[1]


def test_split_authoring_sources_preserve_compiled_runtime_semantics() -> None:
    report = build_report()

    assert report["status"] == "PASS"
    assert report["source_parity"]["semantic_parity"] is True
    assert all(value == "PASS" for value in report["parity"].values())
    assert all(value == "PASS" for value in report["gate"].values())


def test_legacy_registry_is_explicitly_derived_and_not_runtime_input() -> None:
    report = build_report()
    derived = report["derived_view"]

    assert all(value == "PASS" for value in derived.values())
    assert report["legacy_view"]["runtime_input"] is False
    assert report["runtime"]["default_source_path"] == "PASS"
    assert (ROOT / "governance/pipeline").is_dir()
