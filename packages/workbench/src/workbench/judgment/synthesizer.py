"""Canonical Claim -> Judgment synthesis.

The synthesizer accepts only canonical claim envelopes and structured
assessments. Provider/model payloads are adapted upstream and are not part of
this module's authority surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping

from system_runtime.canonical_ids import (
    build_chain,
    build_judgment_record,
    lineage_ids,
    validate_chain,
)

SYNTHESIS_METHOD_VERSION = "judgment_synthesizer.v1"


class JudgmentSynthesisError(ValueError):
    """Raised when a decision cannot be linked to canonical Claims."""


@dataclass(frozen=True)
class ClaimEnvelope:
    """One canonical Claim plus its bounded role in a synthesis."""

    canonical_chain: Mapping[str, Any]
    role: str = "supporting"
    research_only: bool = False
    assessment: Mapping[str, Any] = field(default_factory=dict)

    def validated_chain(self) -> dict[str, Any]:
        chain = dict(self.canonical_chain)
        validate_chain(chain)
        return chain


@dataclass(frozen=True)
class JudgmentRecord:
    """Serializable first-class Judgment value object."""

    payload: Mapping[str, Any]

    @property
    def judgment_id(self) -> str:
        return str(self.payload["judgment_id"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class JudgmentSynthesizer:
    """Synthesize a first-class Judgment from canonical Claim envelopes."""

    method_version = SYNTHESIS_METHOD_VERSION

    def synthesize(
        self,
        *,
        claims: list[ClaimEnvelope],
        as_of: str,
        decision: str,
        claim_ceiling: str,
        confidence: Mapping[str, Any],
        unknowns: list[str] | None = None,
        invalidation_spec_ids: list[str] | None = None,
        policy_version: str = "judgment_policy.v1",
        decision_time: str | None = None,
        status: str | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not claims:
            raise JudgmentSynthesisError("at least one canonical Claim is required")

        validated: list[tuple[ClaimEnvelope, dict[str, Any]]] = [
            (envelope, envelope.validated_chain()) for envelope in claims
        ]
        claim_ids = [chain["claim"]["claim_id"] for _, chain in validated]
        supporting_claim_ids: list[str] = []
        conflicting_claim_ids: list[str] = []
        research_only_claim_ids: list[str] = []
        for envelope, chain in validated:
            claim_id = chain["claim"]["claim_id"]
            research_only = envelope.research_only or bool(
                (chain["claim"].get("provenance") or {}).get("research_only", False)
            )
            if research_only:
                research_only_claim_ids.append(claim_id)
                continue
            role = str(envelope.role).lower()
            if role in {"conflict", "conflicting", "contradiction"}:
                conflicting_claim_ids.append(claim_id)
            elif role in {"support", "supporting", "primary", "context"}:
                supporting_claim_ids.append(claim_id)

        if status is None:
            if conflicting_claim_ids:
                status = "CONFLICTED"
            elif not supporting_claim_ids:
                status = "DIAGNOSTIC_ONLY"
            else:
                status = "SUPPORTED"

        record = build_judgment_record(
            as_of=as_of,
            decision=decision,
            claim_ids=claim_ids,
            supporting_claim_ids=supporting_claim_ids,
            conflicting_claim_ids=conflicting_claim_ids,
            research_only_claim_ids=research_only_claim_ids,
            status=status,
            confidence=confidence,
            claim_ceiling=claim_ceiling,
            unknowns=unknowns or [],
            invalidation_spec_ids=invalidation_spec_ids or [],
            policy_version=policy_version,
            synthesis_method_version=self.method_version,
            decision_time=decision_time or datetime.now(UTC).isoformat(),
            provenance={
                **dict(provenance or {}),
                "producer": str((provenance or {}).get("producer") or "judgment_synthesizer"),
                "claim_count": len(claim_ids),
                "supporting_claim_count": len(supporting_claim_ids),
                "conflicting_claim_count": len(conflicting_claim_ids),
                "research_only_claim_count": len(research_only_claim_ids),
            },
        )

        primary_index = next(
            (index for index, (envelope, _) in enumerate(validated) if not envelope.research_only),
            0,
        )
        canonical_chains = [chain for _, chain in validated]
        primary_chain = canonical_chains[primary_index]
        primary_chain = build_chain(
            observation=primary_chain["observation"],
            measurement=primary_chain["measurement"],
            evidence=primary_chain["evidence"],
            claim=primary_chain["claim"],
            judgment=record,
        )
        canonical_chains[primary_index] = primary_chain
        ids = lineage_ids(primary_chain)
        return {
            "judgment": record,
            "canonical_chain": primary_chain,
            "canonical_chains": canonical_chains,
            "canonical_ids": ids,
            "claim_ids": claim_ids,
            "supporting_claim_ids": supporting_claim_ids,
            "conflicting_claim_ids": conflicting_claim_ids,
            "research_only_claim_ids": research_only_claim_ids,
        }


__all__ = [
    "ClaimEnvelope",
    "JudgmentRecord",
    "JudgmentSynthesisError",
    "JudgmentSynthesizer",
    "SYNTHESIS_METHOD_VERSION",
]
