from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
import warnings

import yaml


class GovernanceWarning(RuntimeWarning):
    """Persistent governance warning — persisted to event log and surfaced in summaries."""


@dataclass(frozen=True)
class AuthorityCheck:
    module: str
    authority: str
    allowed: bool
    reason: str
    event_type: str
    severity: str


class AuthorityRegistry:
    """Load and query the module authority registry (module_authority_registry.yaml)."""

    def __init__(self, registry_path: str | Path):
        self.registry_path = Path(registry_path)
        raw = yaml.safe_load(self.registry_path.read_text(encoding="utf-8")) or {}
        # The consolidated authority_registry.yaml nests modules under a
        # "modules" key.  Flatten so check() can do self.registry.get(module).
        if "modules" in raw and isinstance(raw["modules"], dict):
            self.registry = raw["modules"]
        else:
            self.registry = raw

    def check(self, module: str, authority: str) -> AuthorityCheck:
        """Check whether *module* may exercise *authority*.

        Returns an AuthorityCheck with ``allowed=True`` only when the authority
        is explicitly listed in the module's ``allowed`` set.  Undeclared or
        explicitly forbidden authorities return ``allowed=False``.  This is a
        veto gate — it can block but never grant authority beyond what the
        registry declares.
        """
        rules = self.registry.get(module)
        if rules is None:
            return AuthorityCheck(
                module=module,
                authority=authority,
                allowed=False,
                reason=f"Unknown module: {module}",
                event_type="AUTHORITY_VIOLATION",
                severity="HIGH",
            )
        allowed = set(rules.get("allowed", []))
        forbidden = set(rules.get("forbidden", []))
        if authority in forbidden:
            return AuthorityCheck(
                module=module,
                authority=authority,
                allowed=False,
                reason=f"{authority} is explicitly forbidden for {module}",
                event_type="AUTHORITY_VIOLATION",
                severity="HIGH",
            )
        if authority in allowed:
            return AuthorityCheck(
                module=module,
                authority=authority,
                allowed=True,
                reason=f"{authority} is allowed for {module}",
                event_type="AUTHORITY_CHECK",
                severity="OK",
            )
        return AuthorityCheck(
            module=module,
            authority=authority,
            allowed=False,
            reason=f"{authority} is not declared as allowed for {module}",
            event_type="AUTHORITY_VIOLATION",
            severity="HIGH",
        )


def write_authority_event(
    output_path: str | Path,
    *,
    run_id: str,
    module: str,
    operation: str,
    authority: str,
    allowed: bool,
    reason: str,
) -> None:
    """Append an authority check/violation event to the JSONL trace file.

    Creates parent directories if needed.  Each event includes timestamp,
    run_id, module, operation, authority, allowed status, reason, and
    computed event_type/severity.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": time.time(),
        "run_id": run_id,
        "module": module,
        "operation": operation,
        "authority": authority,
        "allowed": allowed,
        "reason": reason,
        "event_type": "AUTHORITY_CHECK" if allowed else "AUTHORITY_VIOLATION",
        "severity": "OK" if allowed else "HIGH",
    }
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def write_runtime_warning(
    trace_path: str | Path,
    *,
    run_id: str,
    module: str,
    message: str,
    severity: str = "HIGH",
) -> None:
    """Emit a persistent governance warning to both Python warnings and the event log."""
    warnings.warn(message, GovernanceWarning, stacklevel=3)
    write_authority_event(
        trace_path,
        run_id=run_id,
        module=module,
        operation="runtime_warning",
        authority="WARN",
        allowed=False,
        reason=message,
    )
    # Override severity for the persisted event
    trace_path = Path(trace_path)
    if trace_path.exists():
        lines = trace_path.read_text(encoding="utf-8").rstrip().split("\n")
        if lines:
            last = json.loads(lines[-1])
            last["severity"] = severity
            last["event_type"] = "RUNTIME_WARNING"
            lines[-1] = json.dumps(last, ensure_ascii=False)
            trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
