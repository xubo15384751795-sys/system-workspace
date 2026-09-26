"""Acceptance tests for the non-destructive Step 5D layout contract."""
from __future__ import annotations

from tools.audit.layout_contract import build_report


def test_layout_contract_classifies_current_links_without_cleanup() -> None:
    report = build_report()

    assert report["status"] == "PASS"
    assert report["symlink_count"] == report["declared_symlink_count"]
    assert all(value == "PASS" for value in report["gate"].values())
    assert report["note"].startswith("Inventory and contract only")
