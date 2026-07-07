"""registry — governed tool white-list for Structural Research Harness.

Agent tools are NOT bare scripts.  They are registered ToolSpecs that declare
their subsystem, risk level, mutability, allowed modes, prechecks, and postchecks.

Registry provides:
  - list_tools(mode=None) → list[ToolSpec]
  - get_tool(id)         → ToolSpec | None
  - run_tool(id, input, mode, dry_run=False) → ToolResult

Policy enforcement is integrated via hooks/:
  - pre_tool_use.evaluate()  — runs before every invocation
  - post_tool_use hooks      — run after every invocation / failure

All tools return a unified ToolResult structure; failures never leak raw
tracebacks to the calling agent.

Execution order (summary): resolve → mode check → prechecks → classify →
pre_tool_use policy → dry_run → handler → post_failure OR postchecks.
See ``docs/TOOL_EXECUTION_PIPELINE.md`` for the full staged pipeline.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HARNESS_ROOT = Path(__file__).resolve().parent.parent

# ── data structures ─────────────────────────────────────────────────────

@dataclass
class ToolSpec:
    """Governed specification for a single tool."""
    id: str
    description: str
    subsystem: str
    risk_level: str                        # "low" | "medium" | "high"
    read_only: bool
    mutates_artifacts: bool
    requires_approval: bool
    allowed_modes: list[str]               # e.g. ["explore", "verify"]
    required_prechecks: list[str]          # e.g. []
    postchecks: list[str]                  # e.g. ["write_event", "post_verify"]
    handler: Callable[[dict, bool], dict]  # (input, dry_run) → ToolResult dict


@dataclass
class ToolResult:
    """Unified return structure for every tool invocation."""
    ok: bool
    tool_id: str
    artifacts: list[str] = field(default_factory=list)
    summary: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool_id": self.tool_id,
            "artifacts": self.artifacts,
            "summary": self.summary,
            "evidence": self.evidence,
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ── internal registry ───────────────────────────────────────────────────

_registry: dict[str, ToolSpec] = {}


def _register(spec: ToolSpec) -> None:
    if spec.id in _registry:
        raise ValueError(f"ToolSpec already registered: {spec.id}")
    _registry[spec.id] = spec


# ── public API ──────────────────────────────────────────────────────────

def list_tools(mode: str | None = None) -> list[ToolSpec]:
    """List all registered tools, optionally filtered by mode.

    Args:
        mode: If set, only return tools whose ``allowed_modes`` includes *mode*.
              Additionally, when mode is "explore", mutation tools are excluded.
    """
    result: list[ToolSpec] = []
    for spec in _registry.values():
        if mode is not None:
            if mode not in spec.allowed_modes:
                continue
            # explore mode: never show mutation tools
            if mode == "explore" and spec.mutates_artifacts:
                continue
        result.append(spec)
    return result


def get_tool(tool_id: str) -> ToolSpec | None:
    """Look up a single tool by id."""
    return _registry.get(tool_id)


def _is_approved(input: dict) -> bool:
    """Return True when the caller explicitly confirmed a gated action."""
    raw = input.get("approved")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "1", "yes", "approved"}
    return False


def _approval_required_result(
    tool_id: str,
    *,
    rule_id: str,
    reason: str,
    by_hook: str = "registry.approval_gate",
) -> dict:
    return ToolResult(
        ok=False,
        tool_id=tool_id,
        errors=[f"APPROVAL REQUIRED [{rule_id}]: {reason}"],
        evidence={"policy_decision": {
            "decision": "require_approval",
            "rule_id": rule_id,
            "reason": reason,
            "by_hook": by_hook,
        }},
    ).to_dict()


def run_tool(tool_id: str, input: dict, mode: str, *, dry_run: bool = False) -> dict:
    """Run a registered tool and return a unified ToolResult dict.

    Args:
        tool_id: The registered tool id, e.g. "harvester.list_releases"
        input:   Arbitrary keyword arguments for the tool handler.
        mode:    The current agent mode ("explore", "verify", "edit", etc.).
        dry_run: If True, return a success result without executing the handler.

    Returns:
        A dict with keys: ok, tool_id, artifacts, summary, evidence, warnings, errors.
        ``ok`` is False on any failure (not-found, forbidden mode, runtime error).
    """
    # 1. lookup
    spec = _registry.get(tool_id)
    if spec is None:
        return ToolResult(
            ok=False,
            tool_id=tool_id,
            errors=[f"Unknown tool: {tool_id}"],
        ).to_dict()

    # 2. mode check
    if mode not in spec.allowed_modes:
        try:
            from events.system_event_writer import write_permission_deny
            write_permission_deny(
                tool_id=tool_id,
                subsystem=spec.subsystem,
                mode=mode,
                rule_id=f"mode_restriction.{mode}",
                reason=f"Tool '{tool_id}' not allowed in mode '{mode}'",
            )
        except Exception:
            pass
        return ToolResult(
            ok=False,
            tool_id=tool_id,
            errors=[f"POLICY DENY [mode_restriction.{mode}]: Tool '{tool_id}' not allowed in mode '{mode}'. Allowed modes: {spec.allowed_modes}"],
            evidence={"policy_decision": {
                "decision": "deny",
                "rule_id": f"mode_restriction.{mode}",
                "reason": f"Tool '{tool_id}' not allowed in mode '{mode}'",
                "by_hook": "registry.mode_check",
            }},
        ).to_dict()

    # 3. pre-checks (placeholder — postchecks are the immediate priority)
    for pre_id in spec.required_prechecks:
        if pre_id not in _registry:
            return ToolResult(
                ok=False,
                tool_id=tool_id,
                errors=[f"Required precheck not registered: {pre_id}"],
            ).to_dict()

    # ── 3.5 HOOK: policy evaluation ──────────────────────────────────
    _ensure_path()
    try:
        from hooks.risk_classifier import classify
        from hooks.pre_tool_use import evaluate as policy_evaluate

        classification = classify(spec, input, mode)
        decision = policy_evaluate(spec, input, mode, dry_run=dry_run)

        if decision.is_denied:
            # emit hook deny event
            try:
                if decision.by_hook == "pre_tool_use.boundary":
                    from events.system_event_writer import write_boundary_breach
                    write_boundary_breach(
                        tool_id=tool_id, subsystem=spec.subsystem, mode=mode,
                        rule_id=decision.rule_id, reason=decision.reason,
                        classification={
                            "primary": classification.primary_category,
                            "secondary": classification.secondary_categories,
                        },
                    )
                elif decision.by_hook == "feature_flags":
                    from events.system_event_writer import write_feature_gate_deny
                    feature_name = (decision.metadata or {}).get("feature_name", "")
                    write_feature_gate_deny(
                        tool_id=tool_id, subsystem=spec.subsystem, mode=mode,
                        feature_name=feature_name, reason=decision.reason,
                    )
                else:
                    from events.system_event_writer import write_hook_deny
                    write_hook_deny(
                        tool_id=tool_id, subsystem=spec.subsystem, mode=mode,
                        rule_id=decision.rule_id, reason=decision.reason,
                    )
            except Exception:
                pass

            return ToolResult(
                ok=False,
                tool_id=tool_id,
                errors=[f"POLICY DENY [{decision.rule_id}]: {decision.reason}"],
                evidence={"policy_decision": {
                    "decision": decision.decision,
                    "rule_id": decision.rule_id,
                    "reason": decision.reason,
                    "by_hook": decision.by_hook,
                    "classification": {
                        "primary": classification.primary_category,
                        "secondary": classification.secondary_categories,
                        "is_mutation": classification.is_mutation,
                        "is_boundary_crossing": classification.is_boundary_crossing,
                    },
                }},
            ).to_dict()

        if decision.requires_manual_review:
            try:
                from events.system_event_writer import write_hook_require_review
                write_hook_require_review(
                    tool_id=tool_id, subsystem=spec.subsystem, mode=mode,
                    rule_id=decision.rule_id, reason=decision.reason,
                )
            except Exception:
                pass

            return ToolResult(
                ok=False,
                tool_id=tool_id,
                errors=[f"MANUAL_REVIEW REQUIRED [{decision.rule_id}]: {decision.reason}"],
                evidence={"policy_decision": {
                    "decision": decision.decision,
                    "rule_id": decision.rule_id,
                    "reason": decision.reason,
                    "by_hook": decision.by_hook,
                    "classification": {
                        "primary": classification.primary_category,
                        "secondary": classification.secondary_categories,
                    },
                }},
            ).to_dict()

        if decision.decision == "ask" and not _is_approved(input):
            try:
                from events.system_event_writer import write_hook_ask
                write_hook_ask(
                    tool_id=tool_id, subsystem=spec.subsystem, mode=mode,
                    reason=decision.reason,
                )
            except Exception:
                pass
            return _approval_required_result(
                tool_id,
                rule_id=decision.rule_id,
                reason=decision.reason,
                by_hook="registry.ask_gate",
            )

        if decision.decision == "ask":
            try:
                from events.system_event_writer import write_hook_ask
                write_hook_ask(
                    tool_id=tool_id, subsystem=spec.subsystem, mode=mode,
                    reason=decision.reason,
                )
            except Exception:
                pass
    except ImportError:
        classification = None
        decision = None

    if spec.requires_approval and not _is_approved(input):
        return _approval_required_result(
            tool_id,
            rule_id="registry.requires_approval",
            reason=(
                f"Tool '{tool_id}' requires explicit approval. "
                "Re-run with approved=true after human confirmation."
            ),
        )

    # 4. dry-run
    if dry_run:
        return ToolResult(
            ok=True,
            tool_id=tool_id,
            summary=f"[DRY RUN] Would execute {tool_id}",
        ).to_dict()

    # 5. execute (never let a raw traceback escape)
    try:
        result = spec.handler(input, dry_run)
    except Exception as exc:
        error_text = traceback.format_exc().strip()
        safe_error = f"{type(exc).__name__}: {exc}"
        # ── post-failure hook ───────────────────────────────────────
        try:
            from hooks.post_tool_use import post_tool_failure
            post_tool_failure(spec, input, error_text, mode, classification)
        except Exception:
            pass
        # ── write failure event ─────────────────────────────────────
        try:
            from events.system_event_writer import write_tool_failure
            write_tool_failure(
                tool_id=spec.id,
                subsystem=spec.subsystem,
                mode=mode,
                error=error_text,
                classification={
                    "primary": getattr(classification, "primary_category", None) if classification else None,
                } if classification else None,
            )
        except Exception:
            pass
        return ToolResult(
            ok=False,
            tool_id=tool_id,
            errors=[safe_error],
        ).to_dict()

    # 6. postchecks
    if "write_event" in spec.postchecks:
        _postcheck_write_event(spec, input, result, mode, classification, decision)

    if "post_verify" in spec.postchecks:
        _postcheck_post_verify(spec, input, result, mode)

    # 7. ensure caller always gets a dict
    if isinstance(result, ToolResult):
        return result.to_dict()
    if isinstance(result, dict):
        result.setdefault("ok", True)
        result.setdefault("tool_id", tool_id)
        result.setdefault("artifacts", [])
        result.setdefault("summary", "")
        result.setdefault("evidence", {})
        result.setdefault("warnings", [])
        result.setdefault("errors", [])
        return result
    return ToolResult(
        ok=False,
        tool_id=tool_id,
        errors=["Handler returned non-dict, non-ToolResult value"],
    ).to_dict()


def _ensure_path() -> None:
    """Ensure HARNESS_ROOT is on sys.path for hook imports."""
    if str(HARNESS_ROOT) not in sys.path:
        sys.path.insert(0, str(HARNESS_ROOT))


def _postcheck_write_event(
    spec: ToolSpec, input: dict, result: Any, mode: str,
    classification: Any, decision: Any
) -> None:
    try:
        from hooks.post_tool_use import post_tool_use
        post_tool_use(spec, input, result if isinstance(result, dict) else {}, mode, classification)
    except Exception:
        pass

    # Also write structured event for Learning Hub ingestion
    try:
        from events.system_event_writer import write_tool_run
        res_dict = result.to_dict() if isinstance(result, ToolResult) else result
        write_tool_run(
            tool_id=spec.id,
            subsystem=spec.subsystem,
            mode=mode,
            ok=res_dict.get("ok", False) if isinstance(res_dict, dict) else False,
            summary=res_dict.get("summary", "") if isinstance(res_dict, dict) else "",
            evidence=res_dict.get("evidence", {}) if isinstance(res_dict, dict) else {},
            errors=res_dict.get("errors", []) if isinstance(res_dict, dict) else [],
            warnings=res_dict.get("warnings", []) if isinstance(res_dict, dict) else [],
            classification={
                "primary": getattr(classification, "primary_category", None) if classification else None,
                "is_mutation": getattr(classification, "is_mutation", False) if classification else False,
            } if classification else None,
            artifacts=res_dict.get("artifacts", []) if isinstance(res_dict, dict) else [],
            decision=getattr(decision, "decision", "") if decision else "",
            rule_id=getattr(decision, "rule_id", "") if decision else "",
        )
    except Exception:
        pass


def _postcheck_post_verify(
    spec: ToolSpec, input: dict, result: Any, mode: str
) -> None:
    try:
        from hooks.post_tool_use import post_verify
        post_verify(spec, input, result if isinstance(result, dict) else {}, mode)
    except Exception:
        pass
