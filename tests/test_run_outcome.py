"""Acceptance skeleton for WP1A: unified RunOutcome and exit codes.

These tests define the contract that ``system_runtime.run_outcome.RunOutcome``
must satisfy.  They are marked ``xfail(strict=True)`` because the module does
not exist yet; when WP1A lands, the decorator must be removed so the tests
become real acceptance gates.

Exit-code invariants (from the stabilization plan):
- authoritative run returns 0 only after a successful authoritative commit
- registry/schema invalid -> non-zero (configuration failure)
- required step failed or blocked -> non-zero (execution failure)
- execution succeeded but admission rejected -> non-zero (admission failure)
- transaction rollback / recovery -> non-zero (transaction failure)
- mandatory ledger/event sink failure -> non-zero (mandatory-sink failure)
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.xfail(
    strict=True,
    reason="WP1A: RunOutcome not yet implemented",
)


def test_run_outcome_has_required_fields() -> None:
    from system_runtime.run_outcome import RunOutcome  # noqa: F401

    required_fields = {
        "run_id",
        "spec_status",
        "execution_status",
        "failed_steps",
        "blocked_steps",
        "degraded_steps",
        "admission_verdict",
        "publish_status",
        "authority_mode",
        "reason_codes",
        "exit_code",
    }
    import dataclasses

    fields = {f.name for f in dataclasses.fields(RunOutcome)}
    missing = required_fields - fields
    assert not missing, f"RunOutcome missing fields: {missing}"


def test_required_step_failure_returns_nonzero() -> None:
    from system_runtime.run_outcome import RunOutcome

    outcome = RunOutcome(
        run_id="test-run",
        spec_status="OK",
        execution_status="FAILED",
        failed_steps=["harvester"],
        blocked_steps=["freshness"],
        degraded_steps=[],
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
        reason_codes=["REQUIRED_STEP_FAILED"],
        exit_code=0,  # intentionally wrong - test asserts it should be non-zero
    )
    assert outcome.exit_code != 0, "required step failure must return non-zero exit code"


def test_admission_rejection_returns_nonzero() -> None:
    from system_runtime.run_outcome import RunOutcome

    outcome = RunOutcome(
        run_id="test-run",
        spec_status="OK",
        execution_status="SUCCESS",
        failed_steps=[],
        blocked_steps=[],
        degraded_steps=[],
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
        reason_codes=["ADMISSION_REJECTED"],
        exit_code=0,  # intentionally wrong
    )
    assert outcome.exit_code != 0, "admission rejection must return non-zero exit code"


def test_successful_authoritative_commit_returns_zero() -> None:
    from system_runtime.run_outcome import RunOutcome

    outcome = RunOutcome(
        run_id="test-run",
        spec_status="OK",
        execution_status="SUCCESS",
        failed_steps=[],
        blocked_steps=[],
        degraded_steps=[],
        admission_verdict="PASS",
        publish_status="COMMITTED",
        authority_mode="authoritative",
        reason_codes=[],
        exit_code=1,  # intentionally wrong - success must be 0
    )
    assert outcome.exit_code == 0, "successful authoritative commit must return 0"
