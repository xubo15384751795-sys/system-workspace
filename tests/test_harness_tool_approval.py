"""Harness tool approval gates and sanitized failure surfaces."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = ROOT / "packages" / "workbench" / "agents" / "harness"


@pytest.fixture(scope="module")
def harness_registry():
    if str(HARNESS_ROOT) not in sys.path:
        sys.path.insert(0, str(HARNESS_ROOT))
    import tools.learning_hub_tools  # noqa: F401 — register tools
    from tools.registry import _is_approved, get_tool, run_tool

    return {"get_tool": get_tool, "run_tool": run_tool, "is_approved": _is_approved}


def test_is_approved_accepts_explicit_true_values(harness_registry) -> None:
    is_approved = harness_registry["is_approved"]
    assert is_approved({"approved": True}) is True
    assert is_approved({"approved": "yes"}) is True
    assert is_approved({"approved": False}) is False
    assert is_approved({}) is False


def test_requires_approval_blocks_without_confirmation(harness_registry) -> None:
    run_tool = harness_registry["run_tool"]
    result = run_tool("learning_hub.ingest_events", {}, mode="run")
    assert result["ok"] is False
    assert any("APPROVAL REQUIRED" in err for err in result["errors"])


def test_requires_approval_allows_explicit_confirmation(harness_registry) -> None:
    run_tool = harness_registry["run_tool"]
    result = run_tool(
        "learning_hub.ingest_events",
        {"approved": True, "events": []},
        mode="run",
    )
    assert "APPROVAL REQUIRED" not in " ".join(result.get("errors", []))


def test_policy_ask_blocks_without_confirmation(harness_registry) -> None:
    run_tool = harness_registry["run_tool"]
    result = run_tool(
        "learning_hub.write_verification_record",
        {"tool_id": "demo.tool", "summary": "verify gate"},
        mode="verify",
    )
    assert result["ok"] is False
    assert any("APPROVAL REQUIRED" in err for err in result["errors"])


def test_tool_failure_does_not_return_full_traceback(harness_registry) -> None:
    get_tool = harness_registry["get_tool"]
    run_tool = harness_registry["run_tool"]
    spec = get_tool("learning_hub.inspect_queue")
    assert spec is not None
    original = spec.handler

    def _boom(_input: dict, _dry_run: bool):
        raise RuntimeError("sensitive-internal-detail")

    spec.handler = _boom
    try:
        result = run_tool("learning_hub.inspect_queue", {}, mode="explore")
    finally:
        spec.handler = original

    assert result["ok"] is False
    assert result["errors"] == ["RuntimeError: sensitive-internal-detail"]
    joined = " ".join(result["errors"]).lower()
    assert "traceback" not in joined
    assert "file \"" not in joined
