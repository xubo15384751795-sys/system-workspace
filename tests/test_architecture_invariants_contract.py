"""Tests for the Step 1 architecture contract and debt ledger."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from tools.audit.architecture_invariants import scan_architecture

ROOT = Path(__file__).resolve().parents[1]


def test_architecture_contract_declares_all_required_rules() -> None:
    contract = yaml.safe_load(
        (ROOT / "governance" / "architecture_contract.yaml").read_text(encoding="utf-8")
    )
    rule_ids = {item["id"] for item in contract["rules"]}
    assert rule_ids == {f"ARCH-{index:03d}" for index in range(1, 13)}


def test_architecture_contract_keeps_overall_completion_gated() -> None:
    contract = yaml.safe_load(
        (ROOT / "governance" / "architecture_contract.yaml").read_text(encoding="utf-8")
    )
    gate = contract["completion_gate"]
    assert gate["declared_status"] == "NOT_COMPLETE"
    assert set(gate["required_dimensions"]) == {
        "architecture",
        "runtime",
        "portability",
        "semantics",
        "recovery",
        "observation",
    }


def test_architecture_debt_has_required_review_fields_and_frozen_budget() -> None:
    contract = yaml.safe_load(
        (ROOT / "governance" / "architecture_contract.yaml").read_text(encoding="utf-8")
    )
    debt = contract["temporary_debt"]
    entries = debt["entries"]
    assert debt["frozen_count"] == len(entries)
    required = {"id", "rule", "paths", "owner", "migration_target", "reader", "removal_condition"}
    assert all(required <= set(entry) for entry in entries)
    assert len({entry["id"] for entry in entries}) == len(entries)


def test_architecture_scan_has_no_unregistered_violations() -> None:
    report = scan_architecture(ROOT)
    assert report.unregistered == (), [item.as_dict() for item in report.unregistered]


def test_generation_writer_inventory_is_clean() -> None:
    from tools.check_generation_writer_inventory import build_report

    report = build_report(ROOT)
    assert report["verdict"] == "PASS", report


def test_runtime_context_is_the_canonical_context_type() -> None:
    from system_runtime.context import RuntimeContext

    context = RuntimeContext.discover(ROOT)
    assert context.root == ROOT.resolve()
    assert context.paths.root == ROOT.resolve()


def test_archive_adapter_does_not_mutate_sys_path() -> None:
    from verity.runtime._deformation_archive_guard import prepend_archive_src

    before = list(sys.path)
    prepend_archive_src()
    assert sys.path == before
