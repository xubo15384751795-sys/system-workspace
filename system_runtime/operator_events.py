"""Typed operator events emitted at the daily publish boundary.

These events are operational evidence, not decision authority.  They make
provider failure, publish integrity, and authority denial observable with the
same run/release/generation identity used by the outcome and admission token.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA_VERSION = "system.operator_event.v1"


def _event_id(event_type: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {"event_type": event_type, **dict(payload)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{event_type}:{hashlib.sha256(encoded).hexdigest()[:32]}"


def _make_event(
    event_type: str,
    *,
    run_id: str,
    release_id: str | None,
    generation_id: str | None,
    severity: str,
    reason_code: str,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    identity = {
        "run_id": run_id,
        "release_id": release_id,
        "generation_id": generation_id,
        "severity": severity,
        "reason_code": reason_code,
        "details": dict(details),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": _event_id(event_type, identity),
        "event_type": event_type,
        **identity,
    }


def build_operator_events(
    *,
    run_id: str,
    release_id: str | None,
    generation_id: str | None,
    provider_check: Mapping[str, Any] | None = None,
    publish_integrity_verdict: str | None = None,
    diagnostic_publish_verdict: str | None = None,
    decision_authority_verdict: str | None = None,
    publish_status: str | None = None,
    canonical_lineage: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build stable operator events for one completed run boundary.

    ``provider_check`` is the structured minimum-monitoring provider result.
    Only an all-provider failure emits the provider event; ordinary provider
    warnings remain in the typed outcome/monitor payload.  Publish and
    authority events are emitted whenever their verdict is not a successful
    authoritative commit, so an operator can distinguish the failure class.
    """
    events: list[dict[str, Any]] = []
    provider = dict(provider_check or {})
    provider_reason = str(provider.get("reason_code") or "")
    provider_status = str(provider.get("status") or "")
    if provider_reason == "ALL_PROVIDERS_FAILED" or provider.get("all_failed") is True:
        events.append(
            _make_event(
                "provider_all_failed",
                run_id=run_id,
                release_id=release_id,
                generation_id=generation_id,
                severity="error",
                reason_code="ALL_PROVIDERS_FAILED",
                details={
                    "provider_status": provider.get("provider_status"),
                    "monitor_status": provider_status,
                    "monitor_reason_code": provider_reason,
                },
            )
        )

    integrity = str(publish_integrity_verdict or "UNKNOWN").upper()
    diagnostic = str(diagnostic_publish_verdict or "UNKNOWN").upper()
    committed = str(publish_status or "").upper() == "COMMITTED"
    if not committed or integrity != "PASS" or diagnostic != "PASS":
        events.append(
            _make_event(
                "publish_verdict",
                run_id=run_id,
                release_id=release_id,
                generation_id=generation_id,
                severity="error",
                reason_code="PUBLISH_NOT_COMMITTED" if not committed else "PUBLISH_VERDICT_BLOCKED",
                details={
                    "publish_status": publish_status,
                    "publish_integrity_verdict": integrity,
                    "diagnostic_publish_verdict": diagnostic,
                },
            )
        )

    authority = str(decision_authority_verdict or "UNKNOWN").upper()
    if authority in {"BLOCK", "DIAGNOSTIC_ONLY"}:
        events.append(
            _make_event(
                "authority_denial",
                run_id=run_id,
                release_id=release_id,
                generation_id=generation_id,
                severity="warning" if authority == "DIAGNOSTIC_ONLY" else "error",
                reason_code="DECISION_AUTHORITY_DENIED",
                details={"decision_authority_verdict": authority},
            )
        )
    if canonical_lineage:
        # Reader-level dual-read only.  Keep the diagnostic context outside
        # event identity and never let it alter publish/authority verdicts.
        for event in events:
            event["canonical_lineage"] = dict(canonical_lineage)
    return events


__all__ = ["SCHEMA_VERSION", "build_operator_events"]
