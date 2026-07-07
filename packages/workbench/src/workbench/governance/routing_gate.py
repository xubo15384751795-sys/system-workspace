from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class RoutingGateError(RuntimeError):
    """Raised when a routing decision violates promotion gate constraints."""


def latest_routing_decision(path: str | Path) -> Path | None:
    """Return the most recent YAML routing decision file in *path*, or None."""
    path = Path(path)
    if not path.exists():
        return None
    files = sorted(path.glob("*.yaml"))
    if not files:
        return None
    return files[-1]


def load_routing_decision(path: str | Path) -> dict[str, Any]:
    """Load and parse a routing decision YAML file."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def promotion_gate_payload(decision: dict[str, Any]) -> dict[str, Any]:
    """Extract the promotion_gate_decision sub-dict, falling back to the top-level decision."""
    gate = decision.get("promotion_gate_decision")
    if isinstance(gate, dict):
        return gate
    return decision


def validate_routing_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Validate structural integrity of a routing decision.

    Veto check only — raises RoutingGateError on malformed decisions but does
    not grant promotion authority.  Checks: may_promote is explicit, reason or
    decision_id present, blocking decisions declare findings and actions,
    promoting decisions cannot include blocking_findings.
    """
    gate = promotion_gate_payload(decision)
    may_promote = gate.get("may_promote_current_snapshot")
    if may_promote not in {True, False}:
        raise RoutingGateError("Routing decision must explicitly set may_promote_current_snapshot.")
    reason = gate.get("reason") or decision.get("reason") or ""
    decision_id = decision.get("decision_id") or decision.get("task_id")
    if not str(reason).strip() and not decision_id:
        raise RoutingGateError("Routing decision must include a reason or decision_id.")
    blocking_findings = gate.get("blocking_findings", decision.get("blocking_findings", [])) or []
    required_actions = gate.get("required_actions", decision.get("required_actions", [])) or []
    if may_promote is False:
        if not blocking_findings:
            raise RoutingGateError("Blocking routing decision must declare blocking_findings.")
        if not required_actions:
            raise RoutingGateError("Blocking routing decision must declare required_actions.")
    if may_promote is True and blocking_findings:
        raise RoutingGateError("Promoting routing decision cannot include blocking_findings.")
    return gate


def assert_promotion_allowed(routing_dir: str | Path) -> dict[str, Any]:
    """Assert that the latest routing decision permits snapshot promotion.

    Veto gate — raises RoutingGateError if no decision exists, the decision is
    malformed, or may_promote_current_snapshot is not True.  Does not grant
    canonical authority; only confirms the routing decision allows passage.
    """
    latest = latest_routing_decision(routing_dir)
    if latest is None:
        raise RoutingGateError(f"No routing decision found in {routing_dir}; promotion is not allowed.")
    decision = load_routing_decision(latest)
    gate = validate_routing_decision(decision)
    if gate.get("may_promote_current_snapshot") is not True:
        reason = gate.get("reason") or decision.get("reason") or "No reason provided"
        raise RoutingGateError(f"Promotion blocked by routing decision {latest}: {reason}")
    return {
        **decision,
        "promotion_gate_decision": gate,
        "decision_path": str(latest),
    }
