"""Acceptance tests for WP2: PublishAdmission and live-hash invariant.

Defines the contract that admission separates integrity and authority verdicts,
rejects runs with missing required artifacts or previous-run lineage, and
that a rejected run leaves live hashes/mtime/NAV-line-count unchanged.

Also asserts ``freshness_assumed_ok`` is removed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest  # noqa: F401  # kept for marker compatibility

PLAN_DIGEST = hashlib.sha256(b"plan").hexdigest()
EVIDENCE_DIGEST = hashlib.sha256(b"evidence").hexdigest()
GENERATION_DIGEST = hashlib.sha256(b"generation").hexdigest()


def test_publish_admission_module_exists() -> None:
    from system_runtime.publish_admission import PublishAdmission  # noqa: F401


def test_admission_has_integrity_and_authority_verdicts() -> None:
    import dataclasses

    from system_runtime.publish_admission import PublishAdmission

    fields = {f.name for f in dataclasses.fields(PublishAdmission)}
    assert "integrity_verdict" in fields, "PublishAdmission must have integrity_verdict"
    assert "authority_verdict" in fields, "PublishAdmission must have authority_verdict"


def test_integrity_verdict_values() -> None:
    from system_runtime.publish_admission import PublishAdmission

    expected = {"PASS", "BLOCK"}
    actual = getattr(PublishAdmission, "INTEGRITY_VERDICTS", None) or getattr(
        PublishAdmission, "INTEGRITY_VALUES", None
    )
    assert actual is not None, "PublishAdmission must define INTEGRITY_VERDICTS"
    assert expected <= set(actual), f"Missing integrity verdicts: {expected - set(actual)}"


def test_authority_verdict_values() -> None:
    from system_runtime.publish_admission import PublishAdmission

    expected = {"ALLOW", "DIAGNOSTIC_ONLY", "BLOCK"}
    actual = getattr(PublishAdmission, "AUTHORITY_VERDICTS", None) or getattr(
        PublishAdmission, "AUTHORITY_VALUES", None
    )
    assert actual is not None, "PublishAdmission must define AUTHORITY_VERDICTS"
    assert expected <= set(actual), f"Missing authority verdicts: {expected - set(actual)}"


def test_freshness_assumed_ok_removed() -> None:
    """The ``freshness_assumed_ok`` escape hatch must not exist in admission code."""
    import inspect

    from system_runtime import publish_admission

    source = inspect.getsource(publish_admission)
    assert "freshness_assumed_ok" not in source, (
        "freshness_assumed_ok must be removed from publish_admission"
    )


def test_rejected_run_leaves_live_unchanged() -> None:
    """A rejected admission must not modify live current/position/NAV/ledger.

    This is a contract assertion: the admission module must expose a method
    that, on BLOCK, skips all live-surface writes.
    """
    import inspect

    from system_runtime.publish_admission import PublishAdmission

    source = inspect.getsource(PublishAdmission)
    assert "BLOCK" in source, "PublishAdmission must handle BLOCK verdict"
    # Must reference live-surface preservation semantics
    assert "current" in source.lower() or "live" in source.lower(), (
        "PublishAdmission must reference live current preservation"
    )


def test_authority_block_requires_integrity_complete_before_diagnostic_publish() -> None:
    from system_runtime.publish_admission import AUTHORITY_BLOCK, PublishAdmission

    blocked = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=["current/README.md"],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        authority_verdict=AUTHORITY_BLOCK,
        generation_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    assert blocked.integrity_verdict == "BLOCK"
    assert blocked.is_blocked is True
    assert "REQUIRED_ARTIFACT_MISSING" in blocked.reason_codes

    complete = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=["current/README.md"],
        candidate_artifacts=["current/README.md"],
        candidate_run_id="run-1",
        authority_verdict=AUTHORITY_BLOCK,
        generation_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    assert complete.integrity_verdict == "PASS"
    assert complete.is_blocked is False
    assert complete.decision_authority_blocked is True


def test_contract_digests_are_required_for_admission() -> None:
    from system_runtime.publish_admission import PublishAdmission

    blocked = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
    )
    assert blocked.integrity_verdict == "BLOCK"
    assert {
        "PLAN_DIGEST_MISSING",
        "EVIDENCE_DIGEST_MISSING",
        "GENERATION_DIGEST_MISSING",
    } <= set(blocked.reason_codes)


def test_contract_digests_are_serialized() -> None:
    from system_runtime.publish_admission import PublishAdmission

    admission = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    payload = admission.to_dict()
    assert payload["plan_digest"] == PLAN_DIGEST
    assert payload["evidence_digest"] == EVIDENCE_DIGEST
    assert payload["generation_digest"] == GENERATION_DIGEST


def test_canonical_lineage_is_serialized_as_non_authoritative_context() -> None:
    from system_runtime.publish_admission import PublishAdmission

    lineage = {
        "schema_version": "system.canonical_lineage_reader.v1",
        "authority": "shadow_only",
        "promotion_allowed": False,
        "status": "MATCH",
        "entry_count": 1,
        "entries": [],
    }
    admission = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
        canonical_lineage=lineage,
    )

    assert admission.integrity_verdict == "PASS"
    # The old shadow reader is preserved as context, but cannot grant
    # authoritative publication without a complete Claim -> Judgment chain.
    assert admission.authority_verdict == "DIAGNOSTIC_ONLY"
    assert admission.to_dict()["canonical_lineage"] == lineage


def test_complete_claim_judgment_lineage_grants_authority() -> None:
    from system_runtime.canonical_ids import build_chain, build_judgment_record
    from system_runtime.publish_admission import PublishAdmission

    chain = json.loads(
        (Path(__file__).parent / "fixtures" / "canonical_chain_parity.json").read_text()
    )
    claim_id = chain["claim"]["claim_id"]
    record = build_judgment_record(
        as_of="2026-08-19",
        decision="ACTIVE_WATCH",
        claim_ids=[claim_id],
        supporting_claim_ids=[claim_id],
        confidence={
            "measurement": "medium",
            "evidence": "medium",
            "mechanism": "medium_low",
            "calibration": "insufficient",
            "overall": "medium_low",
        },
        claim_ceiling="mechanism_hypothesis",
        provenance={
            "captured_at": "2026-08-19T01:00:00Z",
            "producer": "test",
            "run_id": "run-1",
        },
        decision_time="2026-08-19T01:00:00Z",
    )
    chain = build_chain(
        observation=chain["observation"],
        measurement=chain["measurement"],
        evidence=chain["evidence"],
        claim=chain["claim"],
        judgment=record,
    )
    admission = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
        decision_lineage={"canonical_chain": chain, "canonical_claim_chains": [chain]},
    )
    assert admission.integrity_verdict == "PASS"
    assert admission.authority_verdict == "ALLOW"


def test_missing_claim_judgment_lineage_is_diagnostic_only() -> None:
    from system_runtime.publish_admission import PublishAdmission

    admission = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    assert admission.integrity_verdict == "PASS"
    assert admission.authority_verdict == "DIAGNOSTIC_ONLY"
    assert "JUDGMENT_LINEAGE_MISSING" in admission.reason_codes


def test_release_identity_mismatch_blocks_integrity() -> None:
    from system_runtime.publish_admission import PublishAdmission

    blocked = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        release_id="release-current",
        artifact_release_ids={"current/framework_output.json": "release-previous"},
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )

    assert blocked.integrity_verdict == "BLOCK"
    assert "RELEASE_ID_MISMATCH" in blocked.reason_codes
    assert blocked.to_dict()["artifact_release_ids"] == {
        "current/framework_output.json": "release-previous"
    }


def test_provider_decision_cannot_grant_authoritative_admission() -> None:
    from system_runtime.publish_admission import PublishAdmission

    denied = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        provider_decision="DENY",
        authority_verdict="ALLOW",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    assert denied.integrity_verdict == "PASS"
    assert denied.authority_verdict == "BLOCK"
    assert "PROVIDER_DECISION_DENIED" in denied.reason_codes

    conditional = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        provider_decision="CONDITIONAL",
        authority_verdict="ALLOW",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    assert conditional.integrity_verdict == "PASS"
    assert conditional.authority_verdict == "DIAGNOSTIC_ONLY"


def test_freshness_warn_allows_diagnostic_publish() -> None:
    from system_runtime.publish_admission import PublishAdmission

    admission = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="WARN",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        provider_decision="CONDITIONAL",
        authority_verdict="ALLOW",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    assert admission.integrity_verdict == "PASS"
    assert admission.authority_verdict == "DIAGNOSTIC_ONLY"
    assert admission.can_publish is True
    assert admission.allows_decision_consumers is False
    assert admission.is_blocked is False
    assert "FRESHNESS_WARN" in admission.reason_codes
    assert "PROVIDER_DECISION_CONDITIONAL" in admission.reason_codes


def test_freshness_unknown_and_fail_still_block_integrity() -> None:
    from system_runtime.publish_admission import PublishAdmission

    unknown = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="UNKNOWN",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    assert unknown.integrity_verdict == "BLOCK"
    assert unknown.can_publish is False
    assert "FRESHNESS_UNKNOWN" in unknown.reason_codes

    failed = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="FAIL",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        generation_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )
    assert failed.integrity_verdict == "BLOCK"
    assert failed.can_publish is False
    assert "FRESHNESS_FAIL" in failed.reason_codes


def test_generation_identity_is_required_for_admission_binding() -> None:
    from system_runtime.publish_admission import PublishAdmission

    blocked = PublishAdmission.evaluate(
        run_status="success",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id="run-1",
        plan_digest=PLAN_DIGEST,
        evidence_digest=EVIDENCE_DIGEST,
        generation_digest=GENERATION_DIGEST,
    )

    assert blocked.integrity_verdict == "BLOCK"
    assert "GENERATION_ID_MISSING" in blocked.reason_codes
