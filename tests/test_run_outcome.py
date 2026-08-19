"""Acceptance tests for WP1A: unified RunOutcome and exit codes.

These tests define the contract that ``system_runtime.run_outcome.RunOutcome``
must satisfy.  The module is now implemented; these are real acceptance gates.

Exit-code invariants (from the stabilization plan):
- authoritative run returns 0 only after a successful authoritative commit
- registry/schema invalid -> non-zero (configuration failure)
- required step failed or blocked -> non-zero (execution failure)
- execution succeeded but admission rejected -> non-zero (admission failure)
- transaction rollback / recovery -> non-zero (transaction failure)
- mandatory ledger/event sink failure -> non-zero (mandatory-sink failure)
"""
from __future__ import annotations

import pytest  # noqa: F401  # kept for marker compatibility


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
    from system_runtime.run_outcome import EXIT_EXECUTION_FAILURE, RunOutcome

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
    assert outcome.exit_code == EXIT_EXECUTION_FAILURE


def test_required_step_failure_wins_over_default_admission_block() -> None:
    """A failed execution must not be relabeled as a clean admission rejection."""
    from system_runtime.run_outcome import EXIT_EXECUTION_FAILURE, RunOutcome

    outcome = RunOutcome(
        run_id="failed-before-admission",
        spec_status="OK",
        execution_status="FAILED",
        failed_steps=["harvester"],
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        reason_codes=["REQUIRED_STEP_FAILED"],
    )

    assert outcome.exit_code == EXIT_EXECUTION_FAILURE


def test_admission_rejection_returns_nonzero() -> None:
    from system_runtime.run_outcome import EXIT_ADMISSION_FAILURE, RunOutcome

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
    assert outcome.exit_code == EXIT_ADMISSION_FAILURE


@pytest.mark.parametrize(
    "reason_code",
    ["TRANSACTION_FAILED", "TRANSACTION_ROLLED_BACK", "RECOVERY_REQUIRED"],
)
def test_transaction_failure_reason_wins_over_admission_block(reason_code: str) -> None:
    from system_runtime.run_outcome import EXIT_TRANSACTION_FAILURE, RunOutcome

    outcome = RunOutcome(
        run_id="transaction-failed",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        reason_codes=[reason_code],
    )

    assert outcome.exit_code == EXIT_TRANSACTION_FAILURE


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


def test_status_and_serialization_are_derived_from_same_outcome() -> None:
    from system_runtime.run_outcome import RunOutcome

    outcome = RunOutcome(
        run_id="blocked-late-admission",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
        reason_codes=["ADMISSION_REJECTED"],
    )

    assert outcome.status == "partial_failure"
    serialized = outcome.to_dict()
    assert serialized["status"] == outcome.status
    assert serialized["exit_code"] == outcome.exit_code


def test_diagnostic_noop_is_not_fresh_ready() -> None:
    """Duplicate scheduled wake-up must not claim FRESH_READY."""
    from system_runtime.run_outcome import RunOutcome

    outcome = RunOutcome(
        run_id="scheduled_slot_skip_fixture",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="PASS",
        publish_status="NOT_PUBLISHED",
        authority_mode="diagnostic",
        reason_codes=["SCHEDULE_SLOT_ALREADY_CLAIMED"],
    )
    assert outcome.exit_code == 0
    assert outcome.operational_state == "NOOP_COMPLETED"
    assert outcome.status == "success"
    assert outcome.to_dict()["operational_state"] == "NOOP_COMPLETED"


def test_dry_run_noop_is_not_fresh_ready() -> None:
    """Dry-run must not claim FRESH_READY."""
    from system_runtime.run_outcome import RunOutcome

    outcome = RunOutcome(
        run_id="dry_run",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="PASS",
        publish_status="NOT_PUBLISHED",
        authority_mode="diagnostic",
        reason_codes=[],
    )
    assert outcome.exit_code == 0
    assert outcome.operational_state == "NOOP_COMPLETED"
    assert outcome.status == "success"


def test_fresh_ready_requires_authoritative_committed() -> None:
    """FRESH_READY must require authoritative mode AND COMMITTED publish."""
    from system_runtime.run_outcome import RunOutcome

    # Authoritative + COMMITTED → FRESH_READY (the only valid path)
    ready = RunOutcome(
        run_id="ready-run",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="PASS",
        publish_status="COMMITTED",
        authority_mode="authoritative",
    )
    assert ready.operational_state == "FRESH_READY"

    # Authoritative + NOT_PUBLISHED → NOOP_COMPLETED (not ready)
    not_published = RunOutcome(
        run_id="auth-not-published",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="PASS",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
    )
    # This case hits the publish-not-committed guard in _compute_exit_code (L174)
    # so exit_code != 0, making it a failure path rather than NOOP.
    assert not_published.exit_code != 0
    assert not_published.operational_state != "FRESH_READY"

    # Diagnostic + COMMITTED → NOOP_COMPLETED (diagnostic can't claim readiness)
    diagnostic_committed = RunOutcome(
        run_id="diag-committed",
        spec_status="OK",
        execution_status="SUCCESS",
        admission_verdict="PASS",
        publish_status="COMMITTED",
        authority_mode="diagnostic",
    )
    assert diagnostic_committed.exit_code == 0
    assert diagnostic_committed.operational_state == "NOOP_COMPLETED"
