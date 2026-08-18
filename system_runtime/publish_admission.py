"""Publish admission: integrity + authority verdicts (WP2).

Separates two independent verdicts that gate whether a run's candidate
artifacts may be published to the live ``Output/current/`` surface:

- **integrity_verdict**: PASS or BLOCK.  Checks artifact completeness,
  provenance, and same-run lineage.  A BLOCK here means nothing is published.
- **authority_verdict**: ALLOW, DIAGNOSTIC_ONLY, or BLOCK.  Determines whether
  decision consumers may read the published artifacts.  ALLOW permits decision
  consumers; DIAGNOSTIC_ONLY permits only diagnostic reads; BLOCK denies all.

The legacy escape hatch that allowed publication on unknown/missing freshness
verdicts is removed: unknown verdicts now BLOCK instead of allowing
publication.

An integrity-rejected run must leave the active generation unchanged.  An
authority-rejected but integrity-complete run may publish a diagnostic-only
generation, but decision-authorized consumers must not treat it as admissible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Verdict constants
# ---------------------------------------------------------------------------

# Integrity verdicts
INTEGRITY_PASS = "PASS"
INTEGRITY_BLOCK = "BLOCK"

# Authority verdicts
AUTHORITY_ALLOW = "ALLOW"
AUTHORITY_DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
AUTHORITY_BLOCK = "BLOCK"

# Diagnostic publication is separate from decision authority.  A generation
# may be safely visible as diagnostic-only while remaining unavailable to
# decision-authorized consumers.
DIAGNOSTIC_PASS = "PASS"
DIAGNOSTIC_BLOCK = "BLOCK"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _valid_digest(value: str | None) -> bool:
    """Return whether a contract digest is a canonical SHA-256 hex string."""
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


@dataclass(frozen=True)
class PublishAdmission:
    """Admission verdict for a publish candidate.

    Fields:
        integrity_verdict: ``PASS`` or ``BLOCK``.  Artifact completeness,
            provenance, and same-run lineage check.
        authority_verdict: ``ALLOW``, ``DIAGNOSTIC_ONLY``, or ``BLOCK``.
            Determines whether decision consumers may read the artifacts.
        reason_codes: Machine-readable reason codes for the verdicts.
        required_artifacts_missing: List of required artifacts not found.
        lineage_violations: List of same-run lineage violations.
        freshness_verdict: The freshness verdict from the freshness validator.
        release_id: The selected data release identity, when available.
        artifact_release_ids: Explicit release identities stamped by candidate
            artifacts; mismatches block integrity.
        provider_decision: Provider status-matrix decision that constrains
            decision authority without bypassing diagnostic publication.
        plan_digest: Digest of the compiled plan/policy contract.
        evidence_digest: Digest of run evidence and acquired artifact bytes.
        generation_digest: Digest of the pre-publish generation lineage.
        canonical_lineage: Optional shadow-reader context copied from the
            executed steps. It never participates in a verdict.
    """

    integrity_verdict: str = INTEGRITY_BLOCK
    authority_verdict: str = AUTHORITY_BLOCK
    reason_codes: list[str] = field(default_factory=list)
    required_artifacts_missing: list[str] = field(default_factory=list)
    lineage_violations: list[str] = field(default_factory=list)
    freshness_verdict: str = "UNKNOWN"
    diagnostic_verdict: str = DIAGNOSTIC_PASS
    generation_id: str | None = None
    release_id: str | None = None
    artifact_release_ids: dict[str, str] = field(default_factory=dict)
    provider_decision: str | None = None
    plan_digest: str | None = None
    evidence_digest: str | None = None
    generation_digest: str | None = None
    admission_digest: str | None = None
    canonical_lineage: dict[str, Any] | None = None

    # Class-level verdict sets (for introspection / tests)
    INTEGRITY_VERDICTS = frozenset({INTEGRITY_PASS, INTEGRITY_BLOCK})
    AUTHORITY_VERDICTS = frozenset({AUTHORITY_ALLOW, AUTHORITY_DIAGNOSTIC_ONLY, AUTHORITY_BLOCK})
    DIAGNOSTIC_VERDICTS = frozenset({DIAGNOSTIC_PASS, DIAGNOSTIC_BLOCK})

    @property
    def can_publish(self) -> bool:
        """True only when integrity PASSes (artifacts are safe to publish)."""
        return self.integrity_verdict == INTEGRITY_PASS

    @property
    def allows_decision_consumers(self) -> bool:
        """True only when authority verdict is ALLOW (decision consumers may read)."""
        return self.authority_verdict == AUTHORITY_ALLOW

    @property
    def is_diagnostic_only(self) -> bool:
        """True when authority verdict is DIAGNOSTIC_ONLY (no decision consumption)."""
        return self.authority_verdict == AUTHORITY_DIAGNOSTIC_ONLY

    @property
    def is_blocked(self) -> bool:
        """True when pointer publication is blocked by integrity/diagnostic failure.

        Decision authority is intentionally separate: ``authority_verdict=BLOCK``
        may still publish a same-run diagnostic generation when integrity and
        diagnostic checks pass.
        """
        return (
            self.integrity_verdict == INTEGRITY_BLOCK
            or self.diagnostic_verdict == DIAGNOSTIC_BLOCK
        )

    @property
    def decision_authority_blocked(self) -> bool:
        """True when decision-authorized consumers must not read this generation."""
        return self.authority_verdict == AUTHORITY_BLOCK

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON / RunBundle / notification consumers."""
        payload = {
            "integrity_verdict": self.integrity_verdict,
            "authority_verdict": self.authority_verdict,
            "reason_codes": list(self.reason_codes),
            "required_artifacts_missing": list(self.required_artifacts_missing),
            "lineage_violations": list(self.lineage_violations),
            "freshness_verdict": self.freshness_verdict,
            "diagnostic_verdict": self.diagnostic_verdict,
            "generation_id": self.generation_id,
            "release_id": self.release_id,
            "artifact_release_ids": dict(self.artifact_release_ids),
            "provider_decision": self.provider_decision,
            "plan_digest": self.plan_digest,
            "evidence_digest": self.evidence_digest,
            "generation_digest": self.generation_digest,
            "admission_digest": self.admission_digest,
            # Explicit names used by the serialized pre-publish contract.
            "publish_integrity_verdict": self.integrity_verdict,
            "diagnostic_publish_verdict": self.diagnostic_verdict,
            "decision_authority_verdict": self.authority_verdict,
            "can_publish": self.can_publish,
            "allows_decision_consumers": self.allows_decision_consumers,
            "is_blocked": self.is_blocked,
        }
        if self.canonical_lineage is not None:
            payload["canonical_lineage"] = dict(self.canonical_lineage)
        return payload

    @classmethod
    def evaluate(
        cls,
        *,
        run_status: str,
        freshness_verdict: str,
        required_artifacts: list[str],
        candidate_artifacts: list[str],
        candidate_run_id: str,
        artifact_run_ids: dict[str, str] | None = None,
        diagnostic_verdict: str = DIAGNOSTIC_PASS,
        authority_verdict: str = AUTHORITY_ALLOW,
        generation_id: str | None = None,
        release_id: str | None = None,
        artifact_release_ids: dict[str, str] | None = None,
        provider_decision: str | None = None,
        plan_digest: str | None = None,
        evidence_digest: str | None = None,
        generation_digest: str | None = None,
        canonical_lineage: dict[str, Any] | None = None,
    ) -> PublishAdmission:
        """Evaluate admission from run state and candidate artifacts.

        This replaces the legacy ``should_publish`` function.  Unlike
        ``should_publish``, unknown/missing freshness verdicts do NOT
        fall through to an ``assumed_ok`` path - they BLOCK.

        Args:
            run_status: ``"success"`` or ``"partial_failure"``.
            freshness_verdict: The freshness validator's verdict string
                (``"PASS"``, ``"FAIL"``, ``"STALE"``, ``"VIOLATION"``, or
                unknown).
            required_artifacts: Artifacts that must be present.
            candidate_artifacts: Artifacts present in the candidate.
            candidate_run_id: The current run's ID.
            artifact_run_ids: Map of artifact name -> run ID for lineage check.
        """
        reason_codes: list[str] = []
        missing: list[str] = []
        lineage_violations: list[str] = []
        if not isinstance(generation_id, str) or not generation_id.strip():
            reason_codes.append("GENERATION_ID_MISSING")
            lineage_violations.append("generation_id is required for admission binding")
        contract_digests = {
            "plan_digest": plan_digest,
            "evidence_digest": evidence_digest,
            "generation_digest": generation_digest,
        }
        contract_fields: dict[str, Any] = {
            **contract_digests,
            "release_id": release_id,
            "artifact_release_ids": dict(artifact_release_ids or {}),
            "provider_decision": provider_decision,
        }
        digest_violations = [
            f"{name}: missing or invalid SHA-256 digest"
            for name, value in contract_digests.items()
            if not _valid_digest(value)
        ]
        release_violations: list[str] = []
        if release_id is None and artifact_release_ids:
            release_violations.append("release_id is missing")
        elif release_id is not None:
            if not isinstance(release_id, str) or not release_id.strip():
                release_violations.append("release_id is missing")
            else:
                for artifact, artifact_release_id in (artifact_release_ids or {}).items():
                    if artifact_release_id != release_id:
                        release_violations.append(
                            f"{artifact}: release_id={artifact_release_id!r} != expected={release_id!r}"
                        )
        if digest_violations or lineage_violations or release_violations:
            reason_codes.extend(
                name.upper() + ("_MISSING" if value is None else "_INVALID")
                for name, value in contract_digests.items()
                if not _valid_digest(value)
            )
            if release_violations:
                reason_codes.append(
                    "RELEASE_ID_MISSING"
                    if any(item == "release_id is missing" for item in release_violations)
                    else "RELEASE_ID_MISMATCH"
                )
            return cls(
                integrity_verdict=INTEGRITY_BLOCK,
                authority_verdict=AUTHORITY_BLOCK,
                reason_codes=reason_codes,
                required_artifacts_missing=missing,
                lineage_violations=[*lineage_violations, *digest_violations, *release_violations],
                freshness_verdict=freshness_verdict,
                diagnostic_verdict=diagnostic_verdict,
                generation_id=generation_id,
                canonical_lineage=canonical_lineage,
                **contract_fields,
            )

        if diagnostic_verdict not in cls.DIAGNOSTIC_VERDICTS:
            diagnostic_verdict = DIAGNOSTIC_BLOCK
            reason_codes.append("DIAGNOSTIC_VERDICT_UNKNOWN")

        if authority_verdict not in cls.AUTHORITY_VERDICTS:
            authority_verdict = AUTHORITY_BLOCK
            reason_codes.append("AUTHORITY_VERDICT_UNKNOWN")
        normalized_provider_decision = (
            str(provider_decision).strip().upper() if provider_decision is not None else None
        )
        if normalized_provider_decision == "DENY":
            authority_verdict = AUTHORITY_BLOCK
            reason_codes.append("PROVIDER_DECISION_DENIED")
        elif normalized_provider_decision == "CONDITIONAL":
            if authority_verdict == AUTHORITY_ALLOW:
                authority_verdict = AUTHORITY_DIAGNOSTIC_ONLY
            reason_codes.append("PROVIDER_DECISION_CONDITIONAL")
        elif normalized_provider_decision not in {None, "ALLOW", "CONDITIONAL", "DENY", "BLOCK"}:
            authority_verdict = AUTHORITY_BLOCK
            reason_codes.append("PROVIDER_DECISION_UNKNOWN")
        elif normalized_provider_decision == "BLOCK":
            authority_verdict = AUTHORITY_BLOCK
            reason_codes.append("PROVIDER_DECISION_DENIED")
        if authority_verdict == AUTHORITY_BLOCK:
            reason_codes.append("DECISION_AUTHORITY_BLOCKED")

        # 1. Run status check: only successful runs can pass integrity.
        if run_status != "success":
            reason_codes.append("RUN_NOT_SUCCESS")
            return cls(
                integrity_verdict=INTEGRITY_BLOCK,
                authority_verdict=AUTHORITY_BLOCK,
                reason_codes=reason_codes,
                required_artifacts_missing=missing,
                lineage_violations=lineage_violations,
                freshness_verdict=freshness_verdict,
                diagnostic_verdict=diagnostic_verdict,
                generation_id=generation_id,
                canonical_lineage=canonical_lineage,
                **contract_fields,
            )

        # 2. Freshness check: only PASS passes. Unknown/missing BLOCKs.
        if freshness_verdict.upper() != "PASS":
            reason_codes.append(f"FRESHNESS_{freshness_verdict.upper()}")
            return cls(
                integrity_verdict=INTEGRITY_BLOCK,
                authority_verdict=AUTHORITY_BLOCK,
                reason_codes=reason_codes,
                required_artifacts_missing=missing,
                lineage_violations=lineage_violations,
                freshness_verdict=freshness_verdict,
                diagnostic_verdict=diagnostic_verdict,
                generation_id=generation_id,
                canonical_lineage=canonical_lineage,
                **contract_fields,
            )

        if diagnostic_verdict != DIAGNOSTIC_PASS:
            reason_codes.append("DIAGNOSTIC_PUBLISH_BLOCKED")
            return cls(
                integrity_verdict=INTEGRITY_BLOCK,
                authority_verdict=authority_verdict,
                reason_codes=reason_codes,
                required_artifacts_missing=missing,
                lineage_violations=lineage_violations,
                freshness_verdict=freshness_verdict,
                diagnostic_verdict=diagnostic_verdict,
                generation_id=generation_id,
                canonical_lineage=canonical_lineage,
                **contract_fields,
            )

        # 3. Required artifact completeness check.
        candidate_set = set(candidate_artifacts)
        for name in required_artifacts:
            if name not in candidate_set:
                missing.append(name)
        if missing:
            reason_codes.append("REQUIRED_ARTIFACT_MISSING")
            return cls(
                integrity_verdict=INTEGRITY_BLOCK,
                authority_verdict=AUTHORITY_BLOCK,
                reason_codes=reason_codes,
                required_artifacts_missing=missing,
                lineage_violations=lineage_violations,
                freshness_verdict=freshness_verdict,
                diagnostic_verdict=diagnostic_verdict,
                generation_id=generation_id,
                canonical_lineage=canonical_lineage,
                **contract_fields,
            )

        # 4. Same-run lineage check: all artifacts must belong to this run.
        for name, rid in (artifact_run_ids or {}).items():
            if rid != candidate_run_id:
                lineage_violations.append(f"{name}: run_id={rid} != candidate={candidate_run_id}")
        if lineage_violations:
            reason_codes.append("LINEAGE_MISMATCH")
            return cls(
                integrity_verdict=INTEGRITY_BLOCK,
                authority_verdict=AUTHORITY_BLOCK,
                reason_codes=reason_codes,
                required_artifacts_missing=missing,
                lineage_violations=lineage_violations,
                freshness_verdict=freshness_verdict,
                diagnostic_verdict=diagnostic_verdict,
                generation_id=generation_id,
                canonical_lineage=canonical_lineage,
                **contract_fields,
            )

        # 5. All checks passed: integrity PASS, with authority preserved.
        return cls(
            integrity_verdict=INTEGRITY_PASS,
            authority_verdict=authority_verdict,
            reason_codes=reason_codes,
            required_artifacts_missing=missing,
            lineage_violations=lineage_violations,
            freshness_verdict=freshness_verdict,
            diagnostic_verdict=diagnostic_verdict,
            generation_id=generation_id,
            canonical_lineage=canonical_lineage,
            **contract_fields,
        )
