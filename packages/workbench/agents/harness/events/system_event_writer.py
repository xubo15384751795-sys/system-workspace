"""system_event_writer — delegate runtime observations to Learning Hub.

Peer modules must not append learning events directly. This module forwards
structured observations to `scripts/record_runtime_event.py` (Hub-owned log)
and reads back from `Output/system_learning/runtime/` when needed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
def _resolve_system_root(workbench_root: Path) -> Path:
    """Repo root for both legacy `Workbench/` and `packages/workbench` layouts."""
    parent = workbench_root.parent
    if workbench_root.name.lower() == "workbench" and parent.name == "packages":
        return parent.parent
    return parent

SYSTEM_ROOT = _resolve_system_root(WORKBENCH_ROOT)
RUNTIME_DIR = SYSTEM_ROOT / "Output" / "system_learning" / "runtime"
RECORD_SCRIPT = SYSTEM_ROOT / "scripts" / "record_runtime_event.py"


# ── data structures ─────────────────────────────────────────────────────

@dataclass
class SystemEvent:
    event_id: str = ""
    event_type: str = ""
    severity: str = "info"
    timestamp: str = ""
    subsystem: str = ""
    tool_id: str = ""
    mode: str = ""
    decision: str = ""
    result: str = ""
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    rule_id: str = ""
    reason: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    classification: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v or k in ("event_id", "event_type", "severity", "timestamp")}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)


# ── builders ────────────────────────────────────────────────────────────

def _event(event_type: str, severity: str = "info", **kwargs) -> SystemEvent:
    return SystemEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        severity=severity,
        timestamp=datetime.now(timezone.utc).isoformat(),
        **kwargs,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _s(v: Any) -> str:
    if v is None: return ""
    s = str(v) if not isinstance(v, str) else v
    return s[:2000]


def _l(v: Any) -> list:
    return v if isinstance(v, list) else []


def _d(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


# ── internal write ──────────────────────────────────────────────────────

def _write(event: SystemEvent) -> None:
    if not RECORD_SCRIPT.is_file():
        return
    payload = event.to_dict()
    payload.setdefault("subsystem", payload.get("subsystem") or "harness")
    try:
        subprocess.run(
            [
                sys.executable,
                str(RECORD_SCRIPT),
                "--system-root",
                str(SYSTEM_ROOT),
                "--subsystem",
                str(payload.get("subsystem") or "harness"),
                "--event-type",
                str(payload.get("event_type") or "unspecified"),
                "--severity",
                str(payload.get("severity") or "info"),
                "--source-tool",
                "structural-research-harness",
                "--payload-json",
                json.dumps(payload, default=str, ensure_ascii=False),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        pass


# ── public API: event emitters ──────────────────────────────────────────

def write_tool_run(
    tool_id: str, subsystem: str, mode: str, ok: bool,
    summary: str = "", evidence: dict | None = None,
    errors: list | None = None, warnings: list | None = None,
    classification: dict | None = None, artifacts: list | None = None,
    decision: str = "", rule_id: str = "",
) -> None:
    _write(_event("tool_run", "info",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision=decision or ("allow" if ok else "deny"),
        result="pass" if ok else "fail",
        summary=_s(summary), evidence=_d(evidence),
        errors=_l(errors), warnings=_l(warnings),
        classification=_d(classification), artifacts=_l(artifacts),
        rule_id=rule_id,
    ))


def write_tool_failure(
    tool_id: str, subsystem: str, mode: str, error: str,
    classification: dict | None = None,
) -> None:
    _write(_event("tool_run", "error",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="deny", result="error",
        summary="Tool execution failed", errors=[_s(error)],
        classification=_d(classification),
    ))


def write_permission_decision(
    tool_id: str, subsystem: str, mode: str,
    decision: str, rule_id: str, reason: str,
    risk_category: str = "", severity: str = "info",
) -> None:
    _write(_event("permission_decision", severity,
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision=decision,
        result="blocked" if decision == "deny" else ("flagged" if decision == "ask" else "pass"),
        rule_id=rule_id, reason=_s(reason),
        metadata={"risk_category": risk_category},
    ))


def write_hook_deny(
    tool_id: str, subsystem: str, mode: str,
    rule_id: str, reason: str,
    classification: dict | None = None,
) -> None:
    _write(_event("hook_deny", "warning",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="deny", result="blocked",
        summary="Policy hook denied invocation",
        rule_id=rule_id, reason=_s(reason),
        classification=_d(classification),
    ))


def write_hook_ask(
    tool_id: str, subsystem: str, mode: str,
    reason: str, classification: dict | None = None,
) -> None:
    _write(_event("permission_decision", "info",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="ask", result="flagged",
        summary="Agent prompted for confirmation",
        reason=_s(reason), classification=_d(classification),
    ))


def write_hook_require_review(
    tool_id: str, subsystem: str, mode: str,
    rule_id: str, reason: str,
    classification: dict | None = None,
) -> None:
    _write(_event("permission_decision", "warning",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="require_manual_review", result="blocked",
        summary="Manual review required",
        rule_id=rule_id, reason=_s(reason),
        classification=_d(classification),
    ))


def write_verification_result(
    tool_id: str, subsystem: str, mode: str, ok: bool,
    verdict: str = "", evidence: dict | None = None,
    summary: str = "", blockers: list | None = None,
    residual_risks: list | None = None,
) -> None:
    v = verdict or ("PASS" if ok else "FAIL")
    _write(_event("verification_result",
        "info" if ok else "error",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="verify",
        result="pass" if ok else "fail",
        summary=_s(summary), evidence=_d(evidence),
        metadata={"verdict": v, "blockers": _l(blockers), "residual_risks": _l(residual_risks)},
    ))


def write_boundary_breach(
    tool_id: str, subsystem: str, mode: str,
    rule_id: str, reason: str,
    classification: dict | None = None,
) -> None:
    _write(_event("hook_deny", "warning",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="deny", result="blocked",
        summary="Boundary rule violation detected",
        rule_id=rule_id, reason=_s(reason),
        classification=_d(classification),
        metadata={"breach_type": "boundary"},
    ))


def write_simulated_fallback_blocked(
    tool_id: str, subsystem: str, mode: str,
    rule_id: str, reason: str,
) -> None:
    _write(_event("feature_gate", "warning",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="deny", result="blocked",
        summary="Simulated fallback blocked from production",
        rule_id=rule_id, reason=_s(reason),
        metadata={"feature_name": "simulated_data_fallback"},
    ))


def write_permission_deny(
    tool_id: str, subsystem: str, mode: str,
    rule_id: str, reason: str, risk_category: str = "",
) -> None:
    _write(_event("permission_decision", "warning",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="deny", result="blocked",
        rule_id=rule_id, reason=_s(reason),
        metadata={"risk_category": risk_category},
    ))


def write_feature_gate_deny(
    tool_id: str, subsystem: str, mode: str,
    feature_name: str, reason: str,
    classification: dict | None = None,
) -> None:
    _write(_event("feature_gate", "warning",
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision="deny", result="blocked",
        summary=f"Feature gate blocked: {feature_name}",
        rule_id=f"feature_flag.{feature_name}.deny",
        reason=_s(reason), classification=_d(classification),
        metadata={"feature_name": feature_name},
    ))


def write_routing_decision(
    task_id: str, activated_experts: list[str],
    intentionally_not_activated: list[str],
    verification: str, outputs: list[str],
    unresolved_risks: list[str],
    artifacts_touched: list[str] | None = None,
) -> None:
    _write(_event("routing_decision", "info",
        subsystem="harness",
        summary=f"Routing decision for task {task_id}",
        metadata={
            "task_id": task_id,
            "activated_experts": activated_experts,
            "intentionally_not_activated": intentionally_not_activated,
            "verification": verification,
            "outputs": outputs,
            "unresolved_risks": unresolved_risks,
            "artifacts_touched": _l(artifacts_touched),
        },
    ))


def write_release_attempt(
    release_id: str, tool_id: str, subsystem: str, mode: str,
    decision: str, rule_id: str, reason: str = "",
    release_status: str = "", manual_review_required: bool = False,
) -> None:
    sev = "warning" if decision == "require_manual_review" else "error"
    _write(_event("release_attempt", sev,
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision=decision,
        result="blocked" if decision != "allow" else "pass",
        summary=f"Release attempt: {release_id}",
        rule_id=rule_id, reason=_s(reason),
        metadata={
            "release_id": release_id,
            "release_status": release_status,
            "manual_review_required": manual_review_required,
        },
    ))


def write_snapshot_publish_attempt(
    run_id: str, tool_id: str, subsystem: str, mode: str,
    decision: str, rule_id: str, reason: str = "",
    run_purpose: str = "", feature_name: str = "",
    manual_review_required: bool = False,
) -> None:
    sev = "warning" if decision == "require_manual_review" else "error"
    _write(_event("snapshot_publish_attempt", sev,
        subsystem=subsystem, tool_id=tool_id, mode=mode,
        decision=decision,
        result="blocked" if decision != "allow" else "pass",
        summary=f"Snapshot publish attempt: {run_id}",
        rule_id=rule_id, reason=_s(reason),
        metadata={
            "run_id": run_id, "run_purpose": run_purpose,
            "feature_name": feature_name,
            "manual_review_required": manual_review_required,
        },
    ))


# ── utility: log access ───────────────────────────────────────────────

def list_recent_events(limit: int = 50, hours: float = 24.0) -> list[dict]:
    """Read recent events from the Hub runtime log."""
    if not RUNTIME_DIR.is_dir():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    events: list[dict] = []
    for path in sorted(RUNTIME_DIR.glob("records_*.jsonl"), reverse=True):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = ev.get("timestamp", "")
            if ts:
                try:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if t < cutoff:
                        continue
                except ValueError:
                    pass
            events.append(ev)
            if len(events) >= limit * 3:
                break
        if len(events) >= limit * 3:
            break
    return events[-limit:]


def get_event_log_path(date_str: str | None = None) -> Path:
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return RUNTIME_DIR / f"records_{date_str}.jsonl"


# ── Learning Hub integration: recurrence → improvement queue ─────────

@dataclass
class ImprovementQueueItem:
    issue: str
    subsystem: str
    severity: str
    priority: str
    count: int
    proposed_action: str
    evidence_rule_ids: list[str]


def query_recurring_denials(hours: float = 24.0, threshold: int = 3) -> list[ImprovementQueueItem]:
    """Generate improvement queue items from recurring deny/fail patterns.

    Analyzes recent events to find:
      - Recurring denials (same rule_id ≥ threshold times)
      - Consecutive verification failures
      - Boundary breaches (always generate)
      - Feature gate blocks (≥ 5 in 7 days)

    Returns a list of ImprovementQueueItem suitable for routing into the
    Learning Hub improvement queue.
    """
    events = list_recent_events(limit=500, hours=hours)
    items: list[ImprovementQueueItem] = []

    # Group deny events by rule_id
    deny_events = [e for e in events if e.get("event_type") in ("hook_deny", "permission_decision")
                   and e.get("decision") == "deny"]
    deny_by_rule: Counter = Counter(e.get("rule_id", "") for e in deny_events)
    for rule_id, count in deny_by_rule.items():
        if count >= threshold and rule_id:
            sub = next((e.get("subsystem", "unknown") for e in deny_events if e.get("rule_id") == rule_id), "unknown")
            items.append(ImprovementQueueItem(
                issue=f"Recurring deny: {rule_id}",
                subsystem=sub,
                severity="high" if count >= 5 else "medium",
                priority=str(min(count, 10)),
                count=count,
                proposed_action=f"Investigate recurring deny: {rule_id} ({count} occurrences in {hours}h)",
                evidence_rule_ids=[rule_id],
            ))

    # Consecutive verification failures
    verify_events = [e for e in events if e.get("event_type") == "verification_result"]
    fail_by_tool: Counter = Counter(
        e.get("tool_id", "") for e in verify_events if e.get("result") == "fail"
    )
    for tool_id, count in fail_by_tool.items():
        if count >= 2 and tool_id:
            sub = next((e.get("subsystem", "unknown") for e in verify_events if e.get("tool_id") == tool_id), "unknown")
            items.append(ImprovementQueueItem(
                issue=f"Consecutive verification failures: {tool_id}",
                subsystem=sub,
                severity="high",
                priority=str(min(count, 10)),
                count=count,
                proposed_action=f"Fix verification failure: {tool_id}",
                evidence_rule_ids=[],
            ))

    # Boundary breaches (every one generates)
    breach_events = [e for e in events if e.get("event_type") == "hook_deny"
                     and e.get("metadata", {}).get("breach_type") == "boundary"]
    for ev in breach_events:
        items.append(ImprovementQueueItem(
            issue=f"Boundary breach: {ev.get('rule_id', '')}",
            subsystem=ev.get("subsystem", "unknown"),
            severity="critical",
            priority="1",
            count=1,
            proposed_action=f"Resolve boundary breach: {ev.get('rule_id', '')}",
            evidence_rule_ids=[ev.get("rule_id", "")],
        ))

    # Feature gate blocks (≥ 5 in 7 days)
    gate_events = [e for e in events if e.get("event_type") == "feature_gate"]
    gate_by_feature: Counter = Counter(
        e.get("metadata", {}).get("feature_name", "") for e in gate_events
    )
    for feature_name, count in gate_by_feature.items():
        if count >= 5 and feature_name:
            sub = next((e.get("subsystem", "unknown") for e in gate_events
                        if e.get("metadata", {}).get("feature_name") == feature_name), "unknown")
            items.append(ImprovementQueueItem(
                issue=f"Feature gate blocks accumulating: {feature_name}",
                subsystem=sub,
                severity="low",
                priority=str(min(count // 5, 5)),
                count=count,
                proposed_action=f"Review promotion requirements for: {feature_name}",
                evidence_rule_ids=[],
            ))

    # Sort by severity then count
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda x: (severity_order.get(x.severity, 99), -x.count))
    return items
