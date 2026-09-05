"""post_tool_use — post-execution hooks for the Tool Registry.

Invoked after every successful tool execution.  Handles:
  - write_event:     emits an observability event for every invocation
  - post_verify:     writes verification results to the learning hub

Also provides post_tool_failure for structured error emission.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HARNESS_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class PostHookResult:
    """Result of post-execution hook processing."""
    events_emitted: int = 0
    events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── main hooks ──────────────────────────────────────────────────────────

def post_tool_use(
    tool_spec: Any, input: dict, result: dict, mode: str, classification: Any
) -> PostHookResult:
    """Post-execution hook: write event for observability.

    Called after EVERY successful tool invocation.
    """
    hook_result = PostHookResult()

    tool_id = _get_id(tool_spec)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_id": tool_id,
        "subsystem": _get_attr(tool_spec, "subsystem", "unknown"),
        "mode": mode,
        "ok": result.get("ok", False),
        "summary": result.get("summary", ""),
        "errors": result.get("errors", []),
        "warnings": result.get("warnings", []),
        "classification": {
            "primary": getattr(classification, "primary_category", "unknown"),
            "is_mutation": getattr(classification, "is_mutation", False),
        },
    }
    hook_result.events.append(event)
    hook_result.events_emitted = 1
    return hook_result


def post_tool_failure(
    tool_spec: Any, input: dict, error: str, mode: str, classification: Any
) -> PostHookResult:
    """Post-failure hook: structured error emission.

    Called when a tool invocation throws an exception or returns ok=False.
    """
    hook_result = PostHookResult()

    tool_id = _get_id(tool_spec)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_id": tool_id,
        "subsystem": _get_attr(tool_spec, "subsystem", "unknown"),
        "mode": mode,
        "ok": False,
        "error": error[:1000],  # truncate long tracebacks
        "classification": {
            "primary": getattr(classification, "primary_category", "unknown"),
            "is_mutation": getattr(classification, "is_mutation", False),
        },
        "event_type": "tool_failure",
    }
    hook_result.events.append(event)
    hook_result.events_emitted = 1
    return hook_result


def post_verify(
    tool_spec: Any, input: dict, result: dict, mode: str
) -> PostHookResult:
    """Post-verification hook: record verification results.

    Invoked after harvester.verify_release or deformation.inspect_snapshot.
    Records structured verification evidence for the Learning Hub.
    """
    hook_result = PostHookResult()

    tool_id = _get_id(tool_spec)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_id": tool_id,
        "subsystem": _get_attr(tool_spec, "subsystem", "unknown"),
        "event_type": "verification_result",
        "ok": result.get("ok", False),
        "evidence": result.get("evidence", {}),
        "summary": result.get("summary", ""),
    }
    hook_result.events.append(event)
    hook_result.events_emitted = 1
    return hook_result


# ── helpers ─────────────────────────────────────────────────────────────

def _get_id(spec: Any) -> str:
    if hasattr(spec, "id"):
        return str(spec.id)
    if isinstance(spec, dict):
        return str(spec.get("id", "unknown"))
    return "unknown"


def _get_attr(spec: Any, key: str, default: str = "unknown") -> str:
    if hasattr(spec, key):
        return str(getattr(spec, key))
    if isinstance(spec, dict):
        return str(spec.get(key, default))
    return default
