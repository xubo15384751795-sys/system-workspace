"""Canonical identifiers and schema helpers for the evidence chain.

The runtime has historically used several local identifiers (paths, slugs,
and provider release keys).  Those identifiers are useful as compatibility
labels, but they are not a contract: they can change when a file is moved, a
claim is reworded, or a retry creates a new run directory.

This module defines the small shared identity layer for the Harvester,
measurement, evidence, claim, and judgment surfaces. IDs are deterministic
SHA-256 digests over normalized identity fields. Producer chains may stop at
Claim, but decision-authorized chains must also validate the Claim -> Judgment
link against ``protocols/canonical_chain.schema.json`` before publication.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

from .paths import WorkspacePaths

ROOT = WorkspacePaths.discover().root
CANONICAL_SCHEMA_PATH = ROOT / "protocols" / "canonical_chain.schema.json"
SCHEMA_VERSION = "system.canonical_chain.v1"

CanonicalKind = Literal["observation", "measurement", "evidence", "claim", "judgment", "invalidation"]

ID_PREFIXES: dict[CanonicalKind, str] = {
    "observation": "obs",
    "measurement": "mea",
    "evidence": "evd",
    "claim": "clm",
    "judgment": "jud",
    "invalidation": "inv",
}

AVAILABILITY_STATUSES = frozenset(
    {
        "AVAILABLE",
        "STALE",
        "DELAYED",
        "MISSING",
        "NOT_APPLICABLE",
        "SOURCE_DOWN",
        "SCHEMA_CHANGED",
        "DISCONTINUED",
        "UNKNOWN",
    }
)
DERIVATION_STATUSES = frozenset(
    {"OBSERVED", "ESTIMATED", "INTERPOLATED", "MODELED", "PROXY_DERIVED", "ASSUMED", "NOT_OBSERVABLE"}
)
CLAIM_STATUSES = frozenset(
    {"SUPPORTED", "WEAKLY_SUPPORTED", "CONFLICTED", "STALE", "INSUFFICIENT_DATA", "UNOBSERVABLE", "WATCH"}
)
EVIDENCE_ROLES = frozenset({"PRIMARY", "SECONDARY", "DERIVED", "CONTEXT", "REPRODUCTION"})
JUDGMENT_STATUSES = frozenset(
    {"SUPPORTED", "CONFLICTED", "WATCH", "INSUFFICIENT_DATA", "UNAVAILABLE", "DIAGNOSTIC_ONLY", "BLOCKED"}
)
JUDGMENT_CONFIDENCE_LEVELS = frozenset(
    {"low", "medium_low", "medium", "medium_high", "high", "insufficient", "unknown"}
)


class CanonicalIdError(ValueError):
    """Raised when a canonical identity or chain is invalid."""


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used as an ID preimage."""

    normalized = _normalize(value)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalIdError(f"identity is not JSON-canonical: {exc}") from exc


def canonical_id(kind: CanonicalKind, identity: Mapping[str, Any]) -> str:
    """Create a deterministic, namespaced ID from identity fields.

    Only identity fields belong in this mapping.  Volatile fields such as
    ``generated_at`` and ``run_id`` must stay in provenance and not change the
    identity of the underlying observation or claim.
    """

    if kind not in ID_PREFIXES:
        raise CanonicalIdError(f"unknown canonical ID kind: {kind!r}")
    if not isinstance(identity, Mapping) or not identity:
        raise CanonicalIdError("canonical identity must be a non-empty mapping")
    digest = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:32]
    return f"{ID_PREFIXES[kind]}_{digest}"


def build_observation(
    *,
    canonical_series_id: str,
    observed_at: str | date | datetime,
    value: Any,
    source_id: str,
    unit: str | None = None,
    vintage_at: str | date | datetime | None = None,
    status: str = "AVAILABLE",
    scope: Mapping[str, Any] | None = None,
    source_snapshot_sha256: str | None = None,
    availability: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one canonical observation and its deterministic ID."""

    status = _availability(status)
    observed = _timestamp(observed_at)
    vintage = _timestamp(vintage_at) if vintage_at is not None else observed
    series = _required_text(canonical_series_id, "canonical_series_id")
    source = _required_text(source_id, "source_id")
    identity = {
        "canonical_series_id": series,
        "observed_at": observed,
        "vintage_at": vintage,
        "value": value,
        "unit": unit,
        "scope": dict(scope or {}),
        "status": status,
        "source_id": source,
        "source_snapshot_sha256": source_snapshot_sha256,
    }
    result = {
        "observation_id": canonical_id("observation", identity),
        "canonical_series_id": series,
        "observed_at": observed,
        "vintage_at": vintage,
        "value": _normalize(value),
        "unit": unit,
        "status": status,
        "scope": dict(scope or {}),
        "source": {
            "source_id": source,
            "snapshot_sha256": source_snapshot_sha256,
        },
        "provenance": _provenance(provenance),
    }
    if availability is not None:
        result["availability"] = _availability_contract(availability)
    return result


def build_measurement(
    *,
    observation_ids: Sequence[str],
    measurement_definition: str,
    value: Any,
    unit: str | None = None,
    status: str = "AVAILABLE",
    derivation: str = "OBSERVED",
    confidence: float | None = None,
    method_version: str = "1",
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a measurement derived from one or more observations."""

    ids = _id_list(observation_ids, "obs")
    definition = _required_text(measurement_definition, "measurement_definition")
    status = _availability(status)
    derivation = _derivation(derivation)
    method_version = _required_text(method_version, "method_version")
    identity = {
        "observation_ids": sorted(ids),
        "measurement_definition": definition,
        "method_version": method_version,
        "status": status,
        "derivation": derivation,
    }
    confidence = _confidence(confidence)
    return {
        "measurement_id": canonical_id("measurement", identity),
        "observation_ids": ids,
        "measurement_definition": definition,
        "method_version": method_version,
        "value": _normalize(value),
        "unit": unit,
        "status": status,
        "derivation": derivation,
        "confidence": confidence,
        "provenance": _provenance(provenance),
    }


def build_evidence(
    *,
    measurement_ids: Sequence[str],
    evidence_role: str,
    source_id: str,
    release_id: str | None = None,
    source_snapshot_sha256: str | None = None,
    status: str = "AVAILABLE",
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an evidence record linked to one or more measurements."""

    ids = _id_list(measurement_ids, "mea")
    role = _required_text(evidence_role, "evidence_role").upper()
    if role not in EVIDENCE_ROLES:
        raise CanonicalIdError(f"unknown evidence role: {role}")
    source = _required_text(source_id, "source_id")
    status = _availability(status)
    identity = {
        "measurement_ids": sorted(ids),
        "evidence_role": role,
        "source_id": source,
        "release_id": release_id,
        "source_snapshot_sha256": source_snapshot_sha256,
    }
    return {
        "evidence_id": canonical_id("evidence", identity),
        "measurement_ids": ids,
        "evidence_role": role,
        "status": status,
        "source": {
            "source_id": source,
            "release_id": release_id,
            "snapshot_sha256": source_snapshot_sha256,
        },
        "provenance": _provenance(provenance),
    }


def build_claim(
    *,
    claim_text: str,
    evidence_ids: Sequence[str],
    status: str = "WATCH",
    subject: str | None = None,
    predicate: str | None = None,
    policy_version: str = "1",
    confidence: float | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable claim identity with mutable evidence links.

    Evidence IDs are intentionally *not* part of the claim identity.  A new
    release can add evidence to the same claim without making it a different
    proposition; the new evidence is visible in the claim's linkage fields.
    """

    text = _normalized_text(claim_text, "claim_text")
    ids = _id_list(evidence_ids, "evd", allow_empty=True)
    status = _claim_status(status)
    policy_version = _required_text(policy_version, "policy_version")
    identity = {
        "claim_text": text,
        "subject": subject,
        "predicate": predicate,
        "policy_version": policy_version,
    }
    confidence = _confidence(confidence)
    return {
        "claim_id": canonical_id("claim", identity),
        "claim_text": text,
        "subject": subject,
        "predicate": predicate,
        "policy_version": policy_version,
        "evidence_ids": ids,
        "status": status,
        "confidence": confidence,
        "provenance": _provenance(provenance),
    }


def build_invalidation_spec_id(*, claim_id: str, specification: str) -> str:
    """Create a stable ID for one rendered invalidation specification."""

    claim_ids = _id_list([claim_id], "clm")
    text = _normalized_text(specification, "specification")
    return canonical_id(
        "invalidation",
        {"claim_id": claim_ids[0], "specification": text},
    )


def build_judgment_record(
    *,
    as_of: str,
    decision: str,
    claim_ids: Sequence[str],
    supporting_claim_ids: Sequence[str] = (),
    conflicting_claim_ids: Sequence[str] = (),
    research_only_claim_ids: Sequence[str] = (),
    status: str = "WATCH",
    confidence: Mapping[str, Any] | None = None,
    claim_ceiling: str,
    unknowns: Sequence[str] = (),
    invalidation_spec_ids: Sequence[str] = (),
    policy_version: str = "judgment_policy.v1",
    synthesis_method_version: str = "judgment_synthesizer.v1",
    decision_time: str | date | datetime | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a first-class Judgment record linked to canonical Claims.

    ``decision_time`` and provenance are deliberately excluded from the
    deterministic judgment identity.  Re-running the same policy for the same
    as-of claims therefore preserves the object identity while still recording
    the current capture time.
    """

    claim_refs = _unique_ids(_id_list(claim_ids, "clm"), "claim_ids")
    supporting_refs = _unique_ids(
        _id_list(supporting_claim_ids, "clm", allow_empty=True),
        "supporting_claim_ids",
    )
    conflicting_refs = _unique_ids(
        _id_list(conflicting_claim_ids, "clm", allow_empty=True),
        "conflicting_claim_ids",
    )
    research_refs = _unique_ids(
        _id_list(research_only_claim_ids, "clm", allow_empty=True),
        "research_only_claim_ids",
    )
    for field, refs in {
        "supporting_claim_ids": supporting_refs,
        "conflicting_claim_ids": conflicting_refs,
        "research_only_claim_ids": research_refs,
    }.items():
        unknown = sorted(set(refs) - set(claim_refs))
        if unknown:
            raise CanonicalIdError(f"{field} contains claims not present in claim_ids: {unknown}")
    if set(supporting_refs) & set(conflicting_refs):
        raise CanonicalIdError("a Judgment claim cannot be both supporting and conflicting")
    if set(research_refs) & (set(supporting_refs) | set(conflicting_refs)):
        raise CanonicalIdError("research-only claims cannot support or conflict with a Judgment")
    unclassified = sorted(
        set(claim_refs) - (set(supporting_refs) | set(conflicting_refs) | set(research_refs))
    )
    if unclassified:
        raise CanonicalIdError(f"Judgment claims have no role assignment: {unclassified}")

    status = _judgment_status(status)
    ceiling = _required_text(claim_ceiling, "claim_ceiling")
    decision = _required_text(decision, "decision")
    as_of = _required_text(as_of, "as_of")
    policy_version = _required_text(policy_version, "policy_version")
    synthesis_method_version = _required_text(synthesis_method_version, "synthesis_method_version")
    confidence_data = _judgment_confidence(confidence)
    invalidation_refs = _unique_ids(
        _id_list(invalidation_spec_ids, "inv", allow_empty=True),
        "invalidation_spec_ids",
    )
    unknowns_data = [_normalized_text(item, "unknown") for item in unknowns]
    decision_time_text = _timestamp(decision_time or datetime.now(timezone.utc))
    identity = {
        "as_of": as_of,
        "decision": decision,
        "claim_ids": sorted(claim_refs),
        "supporting_claim_ids": sorted(supporting_refs),
        "conflicting_claim_ids": sorted(conflicting_refs),
        "research_only_claim_ids": sorted(research_refs),
        "status": status,
        "confidence": confidence_data,
        "claim_ceiling": ceiling,
        "unknowns": unknowns_data,
        "invalidation_spec_ids": sorted(invalidation_refs),
        "policy_version": policy_version,
        "synthesis_method_version": synthesis_method_version,
    }
    return {
        "judgment_id": canonical_id("judgment", identity),
        "as_of": as_of,
        "decision_time": decision_time_text,
        "decision": decision,
        "claim_ids": claim_refs,
        "supporting_claim_ids": supporting_refs,
        "conflicting_claim_ids": conflicting_refs,
        "research_only_claim_ids": research_refs,
        "status": status,
        "confidence": confidence_data,
        "claim_ceiling": ceiling,
        "unknowns": unknowns_data,
        "invalidation_spec_ids": invalidation_refs,
        "policy_version": policy_version,
        "synthesis_method_version": synthesis_method_version,
        "provenance": _provenance(provenance),
    }


def build_chain(
    *,
    observation: Mapping[str, Any],
    measurement: Mapping[str, Any],
    evidence: Mapping[str, Any],
    claim: Mapping[str, Any],
    judgment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate a canonical chain envelope.

    A Judgment is optional for compatibility with producer-side evidence
    chains.  Decision-authorized consumers require the extended form.
    """

    chain = {
        "schema_version": SCHEMA_VERSION,
        "observation": dict(observation),
        "measurement": dict(measurement),
        "evidence": dict(evidence),
        "claim": dict(claim),
    }
    if judgment is not None:
        chain["judgment"] = dict(judgment)
    validate_chain(chain)
    return chain


def validate_chain(chain: Mapping[str, Any]) -> None:
    """Validate JSON Schema plus the cross-object reference invariants."""

    if not isinstance(chain, Mapping):
        raise CanonicalIdError("canonical chain must be an object")
    try:
        schema = json.loads(CANONICAL_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalIdError(f"canonical schema unavailable: {CANONICAL_SCHEMA_PATH}: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(dict(chain)),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        detail = "; ".join(_format_error(error) for error in errors)
        raise CanonicalIdError(f"canonical chain failed schema validation: {detail}")

    observation = chain["observation"]
    measurement = chain["measurement"]
    evidence = chain["evidence"]
    claim = chain["claim"]
    judgment = chain.get("judgment")
    expected_observation_id = canonical_id(
        "observation",
        {
            "canonical_series_id": observation["canonical_series_id"],
            "observed_at": observation["observed_at"],
            "vintage_at": observation["vintage_at"],
            "value": observation["value"],
            "unit": observation.get("unit"),
            "scope": observation.get("scope", {}),
            "status": observation["status"],
            "source_id": observation["source"]["source_id"],
            "source_snapshot_sha256": observation["source"].get("snapshot_sha256"),
        },
    )
    expected_measurement_id = canonical_id(
        "measurement",
        {
            "observation_ids": sorted(measurement["observation_ids"]),
            "measurement_definition": measurement["measurement_definition"],
            "method_version": measurement["method_version"],
            "status": measurement["status"],
            "derivation": measurement["derivation"],
        },
    )
    expected_evidence_id = canonical_id(
        "evidence",
        {
            "measurement_ids": sorted(evidence["measurement_ids"]),
            "evidence_role": evidence["evidence_role"],
            "source_id": evidence["source"]["source_id"],
            "release_id": evidence["source"].get("release_id"),
            "source_snapshot_sha256": evidence["source"].get("snapshot_sha256"),
        },
    )
    expected_claim_id = canonical_id(
        "claim",
        {
            "claim_text": " ".join(claim["claim_text"].split()),
            "subject": claim.get("subject"),
            "predicate": claim.get("predicate"),
            "policy_version": claim.get("policy_version", "1"),
        },
    )
    expected_ids = {
        "observation": expected_observation_id,
        "measurement": expected_measurement_id,
        "evidence": expected_evidence_id,
        "claim": expected_claim_id,
    }
    actual_ids = {
        "observation": observation["observation_id"],
        "measurement": measurement["measurement_id"],
        "evidence": evidence["evidence_id"],
        "claim": claim["claim_id"],
    }
    for kind, expected in expected_ids.items():
        if actual_ids[kind] != expected:
            raise CanonicalIdError(f"{kind} ID does not match its canonical identity")
    if observation["observation_id"] not in measurement["observation_ids"]:
        raise CanonicalIdError("measurement does not reference its observation")
    if measurement["measurement_id"] not in evidence["measurement_ids"]:
        raise CanonicalIdError("evidence does not reference its measurement")
    if evidence["evidence_id"] not in claim["evidence_ids"]:
        raise CanonicalIdError("claim does not reference its evidence")
    if judgment is not None:
        validate_judgment_record(judgment)
        if claim["claim_id"] not in judgment["claim_ids"]:
            raise CanonicalIdError("judgment does not reference the chain claim")


def validate_observation(observation: Mapping[str, Any]) -> None:
    """Validate one standalone Observation emitted by a producer sidecar.

    The producer-chain validator remains the authority for complete
    Observation -> Measurement -> Evidence -> Claim envelopes. Harvester
    releases intentionally publish Observation-only JSONL during migration, so
    this helper enforces the same ID and provenance invariants without inventing
    a second chain schema.
    """
    if not isinstance(observation, Mapping):
        raise CanonicalIdError("observation must be an object")
    required = {
        "observation_id",
        "canonical_series_id",
        "observed_at",
        "vintage_at",
        "value",
        "status",
        "source",
        "provenance",
    }
    missing = sorted(required - set(observation))
    if missing:
        raise CanonicalIdError(f"observation missing required fields: {missing}")
    source = observation.get("source")
    if not isinstance(source, Mapping) or not source.get("source_id"):
        raise CanonicalIdError("observation source.source_id is required")
    provenance = observation.get("provenance")
    if not isinstance(provenance, Mapping):
        raise CanonicalIdError("observation provenance is required")
    _provenance(provenance)
    if "availability" in observation:
        _availability_contract(observation["availability"])
    status = _availability(observation["status"])
    expected = canonical_id(
        "observation",
        {
            "canonical_series_id": _required_text(
                observation["canonical_series_id"], "canonical_series_id"
            ),
            "observed_at": _required_text(observation["observed_at"], "observed_at"),
            "vintage_at": _required_text(observation["vintage_at"], "vintage_at"),
            "value": observation["value"],
            "unit": observation.get("unit"),
            "scope": observation.get("scope", {}),
            "status": status,
            "source_id": _required_text(source["source_id"], "source.source_id"),
            "source_snapshot_sha256": source.get("snapshot_sha256"),
        },
    )
    if observation.get("observation_id") != expected:
        raise CanonicalIdError("observation ID does not match its canonical identity")


def validate_claim(claim: Mapping[str, Any]) -> None:
    """Validate a standalone canonical Claim emitted during migration.

    Claim-ladder state is persisted before it has a complete
    Observation -> Measurement -> Evidence chain.  The standalone validator
    therefore checks the claim identity, status, evidence-reference shape and
    provenance without pretending that an empty evidence list is promotion
    authority.
    """
    if not isinstance(claim, Mapping):
        raise CanonicalIdError("claim must be an object")
    required = {"claim_id", "claim_text", "evidence_ids", "status", "provenance"}
    missing = sorted(required - set(claim))
    if missing:
        raise CanonicalIdError(f"claim missing required fields: {missing}")
    _normalized_text(claim["claim_text"], "claim_text")
    _claim_status(claim["status"])
    _id_list(claim["evidence_ids"], "evd", allow_empty=True)
    provenance = claim.get("provenance")
    if not isinstance(provenance, Mapping):
        raise CanonicalIdError("claim provenance is required")
    _provenance(provenance)
    expected = canonical_id(
        "claim",
        {
            "claim_text": " ".join(str(claim["claim_text"]).split()),
            "subject": claim.get("subject"),
            "predicate": claim.get("predicate"),
            "policy_version": claim.get("policy_version", "1"),
        },
    )
    if claim.get("claim_id") != expected:
        raise CanonicalIdError("claim ID does not match its canonical identity")


def validate_judgment_record(judgment: Mapping[str, Any]) -> None:
    """Validate one standalone Judgment record and its deterministic ID."""

    if not isinstance(judgment, Mapping):
        raise CanonicalIdError("judgment must be an object")
    required = {
        "judgment_id",
        "as_of",
        "decision_time",
        "decision",
        "claim_ids",
        "supporting_claim_ids",
        "conflicting_claim_ids",
        "research_only_claim_ids",
        "status",
        "confidence",
        "claim_ceiling",
        "unknowns",
        "invalidation_spec_ids",
        "policy_version",
        "synthesis_method_version",
        "provenance",
    }
    missing = sorted(required - set(judgment))
    if missing:
        raise CanonicalIdError(f"judgment missing required fields: {missing}")
    claim_refs = _unique_ids(_id_list(judgment["claim_ids"], "clm"), "claim_ids")
    supporting_refs = _unique_ids(
        _id_list(judgment["supporting_claim_ids"], "clm", allow_empty=True),
        "supporting_claim_ids",
    )
    conflicting_refs = _unique_ids(
        _id_list(judgment["conflicting_claim_ids"], "clm", allow_empty=True),
        "conflicting_claim_ids",
    )
    research_refs = _unique_ids(
        _id_list(judgment["research_only_claim_ids"], "clm", allow_empty=True),
        "research_only_claim_ids",
    )
    for field, refs in {
        "supporting_claim_ids": supporting_refs,
        "conflicting_claim_ids": conflicting_refs,
        "research_only_claim_ids": research_refs,
    }.items():
        if not set(refs) <= set(claim_refs):
            raise CanonicalIdError(f"{field} contains an unlinked claim")
    if set(supporting_refs) & set(conflicting_refs):
        raise CanonicalIdError("a Judgment claim cannot be both supporting and conflicting")
    if set(research_refs) & (set(supporting_refs) | set(conflicting_refs)):
        raise CanonicalIdError("research-only claims cannot support or conflict with a Judgment")
    unclassified = sorted(
        set(claim_refs) - (set(supporting_refs) | set(conflicting_refs) | set(research_refs))
    )
    if unclassified:
        raise CanonicalIdError(f"Judgment claims have no role assignment: {unclassified}")
    invalidation_refs = _unique_ids(
        _id_list(judgment["invalidation_spec_ids"], "inv", allow_empty=True),
        "invalidation_spec_ids",
    )
    unknowns = [_normalized_text(item, "unknown") for item in judgment["unknowns"]]
    status = _judgment_status(judgment["status"])
    decision = _required_text(judgment["decision"], "decision")
    as_of = _required_text(judgment["as_of"], "as_of")
    policy_version = _required_text(judgment["policy_version"], "policy_version")
    synthesis_method_version = _required_text(
        judgment["synthesis_method_version"], "synthesis_method_version"
    )
    confidence = _judgment_confidence(judgment["confidence"])
    _timestamp(judgment["decision_time"])
    _required_text(judgment["claim_ceiling"], "claim_ceiling")
    provenance = judgment.get("provenance")
    if not isinstance(provenance, Mapping):
        raise CanonicalIdError("judgment provenance is required")
    _provenance(provenance)
    expected = canonical_id(
        "judgment",
        {
            "as_of": as_of,
            "decision": decision,
            "claim_ids": sorted(claim_refs),
            "supporting_claim_ids": sorted(supporting_refs),
            "conflicting_claim_ids": sorted(conflicting_refs),
            "research_only_claim_ids": sorted(research_refs),
            "status": status,
            "confidence": confidence,
            "claim_ceiling": judgment["claim_ceiling"],
            "unknowns": unknowns,
            "invalidation_spec_ids": sorted(invalidation_refs),
            "policy_version": policy_version,
            "synthesis_method_version": synthesis_method_version,
        },
    )
    if judgment.get("judgment_id") != expected:
        raise CanonicalIdError("judgment ID does not match its canonical identity")


def lineage_ids(chain: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact ID block suitable for legacy output envelopes."""

    validate_chain(chain)
    result = {
        "schema_version": SCHEMA_VERSION,
        "observation_id": chain["observation"]["observation_id"],
        "measurement_id": chain["measurement"]["measurement_id"],
        "evidence_id": chain["evidence"]["evidence_id"],
        "claim_id": chain["claim"]["claim_id"],
    }
    if "judgment" in chain:
        result["judgment_id"] = chain["judgment"]["judgment_id"]
    return result


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise CanonicalIdError("canonical identity cannot contain NaN or infinity")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise CanonicalIdError(f"unsupported canonical identity value: {type(value).__name__}")


def _timestamp(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return _required_text(value, "timestamp")


def _provenance(provenance: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(provenance or {})
    captured_at = data.get("captured_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    producer = data.get("producer") or "system_runtime"
    return {
        **data,
        "captured_at": _timestamp(captured_at),
        "producer": _required_text(producer, "provenance.producer"),
    }


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalIdError(f"{field} must be a non-empty string")
    return value.strip()


def _normalized_text(value: Any, field: str) -> str:
    return " ".join(_required_text(value, field).split())


def _availability(value: Any) -> str:
    status = _required_text(value, "status").upper()
    if status not in AVAILABILITY_STATUSES:
        raise CanonicalIdError(f"unknown availability status: {status}")
    return status


def _availability_contract(value: Any) -> dict[str, Any]:
    """Validate the optional explicit observation availability clocks."""
    if not isinstance(value, Mapping):
        raise CanonicalIdError("observation availability must be an object")
    required = {
        "state",
        "observation_date",
        "source_vintage_at",
        "published_at",
        "available_at",
        "retrieved_at",
        "calendar_status",
        "decision_usable",
    }
    missing = sorted(required - set(value))
    if missing:
        raise CanonicalIdError(f"observation availability missing fields: {missing}")
    state = _availability(value["state"])
    calendar = _required_text(value["calendar_status"], "availability.calendar_status").upper()
    if calendar not in {"CONFIGURED", "UNCONFIGURED"}:
        raise CanonicalIdError("availability.calendar_status must be CONFIGURED or UNCONFIGURED")
    if not isinstance(value["decision_usable"], bool):
        raise CanonicalIdError("availability.decision_usable must be boolean")
    if value["decision_usable"] and (
        calendar != "CONFIGURED" or value.get("available_at") in (None, "")
    ):
        raise CanonicalIdError(
            "availability.decision_usable requires configured calendar and available_at"
        )
    available_at = _availability_timestamp(value.get("available_at"), "availability.available_at")
    published_at = _availability_timestamp(value.get("published_at"), "availability.published_at")
    retrieved_at = _availability_timestamp(value.get("retrieved_at"), "availability.retrieved_at")
    if available_at and published_at and available_at < published_at:
        raise CanonicalIdError("availability.available_at cannot precede published_at")
    if retrieved_at is None:
        raise CanonicalIdError("availability.retrieved_at is required")
    return {str(key): _normalize(item) for key, item in value.items()} | {"state": state}


def _availability_timestamp(value: Any, field: str) -> datetime | None:
    """Parse an optional causal clock and require an explicit timezone."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CanonicalIdError(f"{field} must be an ISO timestamp") from exc
    else:
        raise CanonicalIdError(f"{field} must be an ISO timestamp or null")
    if parsed.tzinfo is None:
        raise CanonicalIdError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _derivation(value: Any) -> str:
    status = _required_text(value, "derivation").upper()
    if status not in DERIVATION_STATUSES:
        raise CanonicalIdError(f"unknown derivation status: {status}")
    return status


def _claim_status(value: Any) -> str:
    status = _required_text(value, "claim status").upper()
    if status not in CLAIM_STATUSES:
        raise CanonicalIdError(f"unknown claim status: {status}")
    return status


def _confidence(value: float | None) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise CanonicalIdError("confidence must be a finite number between 0 and 1")
    return float(value)


def _id_list(values: Sequence[str], prefix: str, *, allow_empty: bool = False) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise CanonicalIdError("ID references must be a sequence of strings")
    result = [_required_text(value, "ID reference") for value in values]
    if not result and not allow_empty:
        raise CanonicalIdError("ID references cannot be empty")
    expected = f"{prefix}_"
    invalid = [value for value in result if not value.startswith(expected)]
    if invalid:
        raise CanonicalIdError(f"ID references must start with {expected!r}: {invalid}")
    return result


def _unique_ids(values: Sequence[str], field: str) -> list[str]:
    """Deduplicate references while preserving their first-seen order."""

    result = list(dict.fromkeys(values))
    if not result and field == "claim_ids":
        raise CanonicalIdError("claim_ids cannot be empty")
    return result


def _judgment_status(value: Any) -> str:
    status = _required_text(value, "judgment status").upper()
    if status not in JUDGMENT_STATUSES:
        raise CanonicalIdError(f"unknown judgment status: {status}")
    return status


def _judgment_confidence(value: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise CanonicalIdError("judgment confidence must be an object")
    result: dict[str, str] = {}
    for dimension in ("measurement", "evidence", "mechanism", "calibration", "overall"):
        level = _required_text(value.get(dimension, "unknown"), f"confidence.{dimension}").lower()
        if level not in JUDGMENT_CONFIDENCE_LEVELS:
            raise CanonicalIdError(f"unknown confidence level: {level}")
        result[dimension] = level
    return result


def _format_error(error: Any) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"


__all__ = [
    "AVAILABILITY_STATUSES",
    "CLAIM_STATUSES",
    "CANONICAL_SCHEMA_PATH",
    "CanonicalIdError",
    "DERIVATION_STATUSES",
    "EVIDENCE_ROLES",
    "JUDGMENT_CONFIDENCE_LEVELS",
    "JUDGMENT_STATUSES",
    "SCHEMA_VERSION",
    "build_chain",
    "build_claim",
    "build_evidence",
    "build_invalidation_spec_id",
    "build_judgment_record",
    "build_measurement",
    "build_observation",
    "canonical_id",
    "canonical_json",
    "lineage_ids",
    "validate_claim",
    "validate_observation",
    "validate_judgment_record",
    "validate_chain",
]
