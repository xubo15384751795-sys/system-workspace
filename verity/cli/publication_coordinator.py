"""Publication and admission helpers for the daily application.

The daily application owns the publication decision.  This module owns only
the pure boundary helpers used to validate candidate lineage, map requested
authority, and refresh compatibility indexes after a pointer decision.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from system_runtime.publish_admission import (
    AUTHORITY_ALLOW,
    AUTHORITY_BLOCK,
    AUTHORITY_DIAGNOSTIC_ONLY,
)
from system_runtime.publish_transaction import PublishTransaction, TransactionState
from system_runtime.run_outcome import (
    REASON_RECOVERY_REQUIRED,
    REASON_TRANSACTION_FAILED,
    REASON_TRANSACTION_ROLLED_BACK,
)


def diagnostic_route_policies(steps: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return provider route policies that cannot carry decision authority."""
    policies: list[dict[str, object]] = []
    for step in steps:
        provider_outcome = step.get("provider_outcome")
        if not isinstance(provider_outcome, dict):
            continue
        route_policy = provider_outcome.get("route_policy")
        if isinstance(route_policy, dict) and bool(route_policy.get("diagnostic_only")):
            policies.append(dict(route_policy))
    return policies


def transaction_failure_reasons(
    transaction: PublishTransaction | None,
    *,
    commit_attempted: bool,
) -> list[str]:
    """Map a failed generation commit to the authoritative typed reason."""

    if transaction is None or not commit_attempted or transaction.state == TransactionState.COMMITTED:
        return []
    if transaction.state == TransactionState.RECOVERY_REQUIRED:
        return [REASON_RECOVERY_REQUIRED]
    if transaction.state == TransactionState.ROLLED_BACK:
        return [REASON_TRANSACTION_ROLLED_BACK]
    return [REASON_TRANSACTION_FAILED]


def refresh_live_system_index(*, isolated_output: bool) -> None:
    """Rebuild Data/system_index from committed Output after pointer decision."""
    if isolated_output:
        return
    from workbench.surfaces.build_system_index import persist_index

    persist_index()


def requested_authority_from_decision(decision_payload: dict[str, object] | None) -> str:
    """Map a decision artifact to explicit publication authority."""
    if not decision_payload:
        return AUTHORITY_BLOCK
    if decision_payload.get("decision") in {"WATCH", "WATCH_ONLY"}:
        return AUTHORITY_DIAGNOSTIC_ONLY
    try:
        effective_size = float(decision_payload.get("effective_size") or 0)
    except (TypeError, ValueError):
        return AUTHORITY_BLOCK
    if not math.isfinite(effective_size):
        return AUTHORITY_BLOCK
    return AUTHORITY_ALLOW if effective_size > 0 else AUTHORITY_DIAGNOSTIC_ONLY


def candidate_identity_contracts(
    generation_dir: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Collect explicit run/release identities emitted by candidate JSON.

    A candidate can contain a syntactically valid artifact copied from an old
    run. The generation checksum alone cannot detect that semantic reuse, so
    admission also checks identities that producers explicitly stamp into JSON
    or provenance. Missing optional identity fields remain the producer's
    responsibility; any identity that is present but disagrees is fatal.
    """
    run_ids: dict[str, str] = {}
    release_ids: dict[str, str] = {}

    def walk(value: object, relative: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                location = f"{relative}.{key}" if relative else str(key)
                if key in {"run_id", "bundle_run_id", "generation_id"}:
                    if isinstance(child, str) and child.strip():
                        run_ids[location] = child
                elif key in {"release_id", "source_release_id"}:
                    if isinstance(child, str) and child.strip():
                        release_ids[location] = child
                walk(child, location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{relative}[{index}]")

    for path in sorted(generation_dir.rglob("*.json")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        walk(payload, str(path.relative_to(generation_dir)))
    return run_ids, release_ids


def candidate_decision_lineage(generation_dir: Path) -> dict[str, object] | None:
    """Read the candidate Judgment chain for authority admission.

    The publish transaction still checks every candidate byte. This helper
    only selects the decision-facing lineage envelope; PublishAdmission is the
    validator and authority owner.
    """

    path = generation_dir / "judgment" / "latest.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("canonical_chain"), dict):
        return None
    result: dict[str, object] = {"canonical_chain": payload["canonical_chain"]}
    if isinstance(payload.get("canonical_claim_chains"), list):
        result["canonical_claim_chains"] = payload["canonical_claim_chains"]
    return result
