"""Read-only canonical-lineage context for runtime consumers.

SYS-21 is migrating readers incrementally.  This module gives publish,
authority, and notification consumers one bounded way to *observe* the
canonical Observation -> Measurement -> Evidence -> Claim -> Judgment IDs
while their existing run/release/generation contracts remain authoritative.

The helper is deliberately non-authoritative: it never creates IDs, changes a
verdict, or treats missing lineage as a successful migration.  It only
validates lineage already attached to successful/degraded step records.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from system_runtime.canonical_ids import lineage_ids

SCHEMA_VERSION = "system.canonical_lineage_reader.v1"
SHADOW_AUTHORITY = "shadow_only"
_LINEAGE_KEYS = ("observation_id", "measurement_id", "evidence_id", "claim_id")
_VALID_STEP_STATUSES = frozenset({"success", "degraded"})


def _compact_ids(value: Mapping[str, Any]) -> dict[str, str] | None:
    """Return the producer IDs and optional Judgment ID when complete."""

    ids: dict[str, str] = {}
    for key in _LINEAGE_KEYS:
        candidate = value.get(key)
        if not isinstance(candidate, str) or not candidate:
            return None
        ids[key] = candidate
    if "judgment_id" in value:
        candidate = value.get("judgment_id")
        if not isinstance(candidate, str) or not candidate:
            return None
        ids["judgment_id"] = candidate
    return ids


def summarize_step_lineage(
    steps: Sequence[Mapping[str, Any]],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Summarize validated canonical lineage already present in step records.

    Only successful/degraded steps are eligible.  A full chain is revalidated
    and its compact IDs are compared with the transport ``canonical_ids``
    block.  The result is diagnostic metadata for readers; callers must not
    use ``status`` as a publish or decision verdict.
    """

    entries: list[dict[str, Any]] = []
    violations: list[str] = []
    expected_run_id = str(run_id or "").strip() or None

    for step in steps:
        if not isinstance(step, Mapping):
            continue
        if str(step.get("status") or "") not in _VALID_STEP_STATUSES:
            continue
        compact = step.get("canonical_ids")
        chain = step.get("canonical_chain")
        if not isinstance(compact, Mapping) and not isinstance(chain, Mapping):
            continue

        step_name = str(step.get("step") or "unknown")
        if isinstance(chain, Mapping):
            try:
                derived = lineage_ids(chain)
            except (TypeError, ValueError):
                violations.append(f"{step_name}:canonical_chain_invalid")
                continue
        else:
            derived = None

        compact_ids = _compact_ids(compact) if isinstance(compact, Mapping) else None
        if compact_ids is None:
            violations.append(f"{step_name}:canonical_ids_incomplete")
            continue
        if derived is None:
            violations.append(f"{step_name}:canonical_chain_missing")
            continue

        expected_ids = {
            key: str(value)
            for key, value in derived.items()
            if key != "schema_version"
        }
        if compact_ids != expected_ids:
            violations.append(f"{step_name}:canonical_ids_chain_mismatch")
            continue

        entry: dict[str, Any] = {
            "step": step_name,
            "canonical_ids": compact_ids,
        }
        source_path = step.get("canonical_source_path")
        if source_path:
            entry["canonical_source_path"] = str(source_path)
        entries.append(entry)

    if violations:
        status = "PARITY_MISMATCH"
    elif entries:
        status = "MATCH"
    else:
        status = "UNAVAILABLE"

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "authority": SHADOW_AUTHORITY,
        "promotion_allowed": False,
        "status": status,
        "entry_count": len(entries),
        "entries": entries,
    }
    if expected_run_id:
        result["run_id"] = expected_run_id
    if violations:
        result["violations"] = violations[:20]
    return result


__all__ = ["SCHEMA_VERSION", "SHADOW_AUTHORITY", "summarize_step_lineage"]
