"""Bounded shadow comparison for orchestration executor migration.

This module deliberately does not execute either path.  Callers provide the
results already produced by a Dagster and a direct/compatibility executor for
the same compiled plan.  The returned report is diagnostic-only and therefore
cannot become a publish or promotion authority.

The distinction matters during SYS-21: execution parity can be proven before
the scheduler's readers are migrated, while missing canonical lineage remains
visible instead of being silently treated as a successful migration.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "system.orchestration_shadow_parity.v1"
SHADOW_AUTHORITY = "shadow_only"

_LINEAGE_KEYS = (
    "observation_id",
    "measurement_id",
    "evidence_id",
    "claim_id",
    "judgment_id",
)
_PRODUCER_LINEAGE_KEYS = _LINEAGE_KEYS[:4]
_RESULT_FIELDS = (
    "step",
    "status",
    "blocked_by",
    "degraded",
    "degraded_by",
    "skip_reason",
    "error",
)


@dataclass(frozen=True)
class ShadowParityReport:
    """Structured, non-authoritative comparison output."""

    schema_version: str
    authority: str
    promotion_allowed: bool
    plan_digest: str | None
    execution_parity: str
    canonical_lineage_parity: str
    status: str
    step_count: int
    mismatches: tuple[dict[str, Any], ...]
    legacy_canonical_ids: dict[str, str]
    dagster_canonical_ids: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe report for tests or a future diagnostic sink."""
        return asdict(self)


def _normalise_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only deterministic execution semantics for parity comparison."""
    normalised: dict[str, Any] = {}
    for field in _RESULT_FIELDS:
        if field not in result:
            continue
        value = result[field]
        if field in {"blocked_by", "degraded_by"}:
            value = sorted(str(item) for item in (value or []))
        elif field == "degraded":
            value = bool(value)
        elif value is not None:
            value = str(value)
        normalised[field] = value
    return normalised


def _extract_canonical_ids(value: Any) -> dict[str, str]:
    """Extract only canonical lineage IDs from a result payload.

    The extractor accepts both the compact ``canonical_ids`` block and a full
    ``canonical_chain``.  It intentionally ignores legacy IDs and arbitrary
    strings so a shadow report cannot claim canonical coverage by accident.
    """
    found: dict[str, str] = {}

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            compact = node.get("canonical_ids")
            if isinstance(compact, Mapping):
                for key in _LINEAGE_KEYS:
                    candidate = compact.get(key)
                    if isinstance(candidate, str) and candidate.startswith(
                        ("obs_", "mea_", "evd_", "clm_")
                    ):
                        found[key] = candidate
            for key in _LINEAGE_KEYS:
                candidate = node.get(key)
                prefix = {
                    "observation_id": "obs_",
                    "measurement_id": "mea_",
                    "evidence_id": "evd_",
                    "claim_id": "clm_",
                    "judgment_id": "jud_",
                }[key]
                if isinstance(candidate, str) and candidate.startswith(prefix):
                    found[key] = candidate
            for child in node.values():
                visit(child)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for child in node:
                visit(child)

    visit(value)
    return {key: found[key] for key in _LINEAGE_KEYS if key in found}


def compare_sequence_results(
    legacy_results: Sequence[Mapping[str, Any]],
    dagster_results: Sequence[Mapping[str, Any]],
    *,
    plan_digest: str | None = None,
) -> ShadowParityReport:
    """Compare two already-executed sequence result lists.

    ``legacy`` is a compatibility label for the non-Dagster/direct result;
    it does not grant that executor authority.  A report with matching step
    semantics but no canonical IDs is deliberately reported as
    ``EXECUTION_MATCH_CANONICAL_UNAVAILABLE`` rather than a full migration
    pass.
    """
    mismatches: list[dict[str, Any]] = []
    if len(legacy_results) != len(dagster_results):
        mismatches.append(
            {
                "kind": "step_count",
                "legacy": len(legacy_results),
                "dagster": len(dagster_results),
            }
        )

    for index, (legacy, dagster) in enumerate(
        zip(legacy_results, dagster_results, strict=False), start=1
    ):
        left = _normalise_result(legacy)
        right = _normalise_result(dagster)
        if left != right:
            mismatches.append(
                {
                    "kind": "step_result",
                    "index": index,
                    "legacy": left,
                    "dagster": right,
                }
            )

    legacy_ids = _extract_canonical_ids(legacy_results)
    dagster_ids = _extract_canonical_ids(dagster_results)
    if not legacy_ids and not dagster_ids:
        canonical_parity = "NOT_PRESENT"
    elif (
        legacy_ids == dagster_ids
        and set(legacy_ids) >= set(_PRODUCER_LINEAGE_KEYS)
        and set(legacy_ids) <= set(_LINEAGE_KEYS)
    ):
        canonical_parity = "MATCH"
    else:
        canonical_parity = "MISMATCH"
        mismatches.append(
            {
                "kind": "canonical_lineage",
                "legacy": legacy_ids,
                "dagster": dagster_ids,
            }
        )

    execution_parity = "MATCH" if not mismatches or (
        len(mismatches) == 1 and mismatches[0].get("kind") == "canonical_lineage"
    ) else "MISMATCH"
    if execution_parity == "MISMATCH" or canonical_parity == "MISMATCH":
        status = "MISMATCH"
    elif canonical_parity == "MATCH":
        status = "PASS"
    else:
        status = "EXECUTION_MATCH_CANONICAL_UNAVAILABLE"

    return ShadowParityReport(
        schema_version=SCHEMA_VERSION,
        authority=SHADOW_AUTHORITY,
        promotion_allowed=False,
        plan_digest=plan_digest,
        execution_parity=execution_parity,
        canonical_lineage_parity=canonical_parity,
        status=status,
        step_count=max(len(legacy_results), len(dagster_results)),
        mismatches=tuple(mismatches),
        legacy_canonical_ids=legacy_ids,
        dagster_canonical_ids=dagster_ids,
    )


__all__ = ["SCHEMA_VERSION", "ShadowParityReport", "compare_sequence_results"]
