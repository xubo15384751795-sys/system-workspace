"""Operator-bound task-router tool runs (index write / refresh / live replay).

Kept out of merge-gate via STATEFUL_ROOT_TESTS.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = ROOT / "packages" / "workbench" / "agents" / "harness"
SYSTEM_ENTRY = HARNESS_ROOT / "entrypoints" / "system.py"


def _tools(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SYSTEM_ENTRY), "tools", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def test_build_system_index_tool_writes_expected_outputs() -> None:
    proc = _tools("run", "data_output.build_system_index", "--mode", "run", "--json")
    payload = json.loads(proc.stdout)
    outputs = payload["evidence"]["system_index"]["outputs"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "data_output.build_system_index"
    assert sorted(payload["artifacts"]) == [
        "Data/system_index/latest.json",
        "Data/system_index/lineage_graph.json",
        "Data/system_index/system_catalog.json",
    ]
    assert all(item["exists"] for item in outputs.values())


def test_refresh_current_tool_updates_contract_artifacts() -> None:
    proc = _tools("run", "workbench.refresh_current", "--mode", "run", "--json")
    payload = json.loads(proc.stdout)
    refresh = payload["evidence"]["current_refresh"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "workbench.refresh_current"
    assert refresh["required_artifacts"]["00_READ_ME_FIRST.md"]["exists"] is True
    assert refresh["required_artifacts"]["framework_output.json"]["exists"] is True


def test_evaluate_replay_tool_reports_current_run_warnings() -> None:
    proc = _tools(
        "run",
        "deformation.evaluate_replay",
        "run_id=2026-04-22_WEEKLY",
        "--mode",
        "verify",
        "--json",
    )
    payload = json.loads(proc.stdout)
    replay = payload["evidence"]["replay_evaluation"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "deformation.evaluate_replay"
    assert replay["run_id"] == "2026-04-22_WEEKLY"
    assert replay["verdict"] == "WARN"
    assert replay["snapshot_match"] is True
    assert replay["artifacts"]["operator_trace"]["header_status"] == "missing"
    assert "operator_trace.jsonl has no per-operator records" in payload["warnings"]


def test_promote_snapshot_preflight_reports_blockers_without_mutation() -> None:
    proc = _tools(
        "run",
        "artifact.promote_snapshot_preflight",
        "run_id=2026-04-22_WEEKLY",
        "--mode",
        "verify",
        "--json",
    )
    payload = json.loads(proc.stdout)
    preflight = payload["evidence"]["preflight"]

    assert payload["ok"] is True
    assert payload["tool_id"] == "artifact.promote_snapshot_preflight"
    assert preflight["run_id"] == "2026-04-22_WEEKLY"
    assert preflight["manual_review_required"] is True
    assert "blockers" in preflight


def test_promote_snapshot_requires_manual_review_in_release_mode() -> None:
    proc = _tools(
        "run",
        "artifact.promote_snapshot",
        "run_id=2026-04-22_WEEKLY",
        "--mode",
        "release",
        "--json",
        check=False,
    )
    payload = json.loads(proc.stdout)
    decision = payload["evidence"]["policy_decision"]

    assert proc.returncode == 1
    assert payload["ok"] is False
    assert decision["decision"] == "require_manual_review"
    assert decision["classification"]["primary"] == "snapshot_publish"
