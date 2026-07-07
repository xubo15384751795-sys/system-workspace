"""post_verify — post-verification hook for the Tool Registry.

Invoked after harvester.verify_release or deformation.validate_snapshot.
Records structured verification evidence and writes a verification_result
event to the Learning Hub event log.

Also provides the verify workflow integration point: after a verification
tool runs, this hook ensures the event is persisted for later audit and
for the Learning Hub's recurrence analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hooks.post_tool_use import PostHookResult


def post_verify(
    tool_spec: Any, input: dict, result: dict, mode: str
) -> PostHookResult:
    """Post-verification hook: record verification results and emit event.

    Called after harvester.verify_release or deformation.validate_snapshot
    completes.  Extracts check-level evidence, determines PASS/FAIL/PARTIAL
    verdict, and writes a verification_result event.
    """
    hook_result = PostHookResult()

    tool_id = _get_id(tool_spec)
    subsystem = _get_attr(tool_spec, "subsystem", "unknown")
    ok = result.get("ok", False)
    evidence = result.get("evidence", {})
    checks = evidence.get("checks", [])
    all_passed = all(c.get("passed", False) for c in checks) if checks else ok

    # Determine verdict
    if not checks:
        verdict = "PASS" if ok else "FAIL"
    elif all_passed:
        verdict = "PASS"
    elif any(c.get("passed", False) for c in checks):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    # Build verification event
    event = {
        "event_type": "verification_result",
        "tool_id": tool_id,
        "subsystem": subsystem,
        "mode": mode,
        "verdict": verdict,
        "result": "pass" if all_passed else "fail",
        "summary": result.get("summary", ""),
        "evidence": {
            "checks": checks,
            "total": len(checks),
            "passed": sum(1 for c in checks if c.get("passed", False)),
            "failed": sum(1 for c in checks if not c.get("passed", False)),
        },
        "blockers": [c for c in checks if not c.get("passed", False)],
        "residual_risks": [] if verdict != "PARTIAL" else [
            c.get("check", "unknown") for c in checks if not c.get("passed", False)
        ],
        "timestamp": _now_iso(),
    }

    # Emit to Learning Hub event writer
    try:
        from events.system_event_writer import write_verification_result
        write_verification_result(
            tool_id=tool_id,
            subsystem=subsystem,
            mode="verify",
            ok=all_passed,
            verdict=verdict,
            evidence=event["evidence"],
            summary=event["summary"],
            blockers=event["blockers"],
            residual_risks=event["residual_risks"],
        )
        event["event_written"] = True
    except Exception:
        event["event_written"] = False

    hook_result.events.append(event)
    hook_result.events_emitted = 1
    return hook_result


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _get_id(spec: Any) -> str:
    if hasattr(spec, "id"):
        return spec.id
    if isinstance(spec, dict):
        return spec.get("id", "unknown")
    return "unknown"


def _get_attr(spec: Any, key: str, default: str = "unknown") -> str:
    if hasattr(spec, key):
        return getattr(spec, key)
    if isinstance(spec, dict):
        return spec.get(key, default)
    return default
