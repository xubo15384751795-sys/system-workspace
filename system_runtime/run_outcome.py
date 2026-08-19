"""Unified run outcome and exit-code authority (WP1A).

A single :class:`RunOutcome` captures the authoritative state of a daily run.
Every consumer -- CLI, Dagster, shell wrapper, launchd, RunBundle, notification,
runtime event -- must serialize the same object rather than re-deriving status
independently.

Exit-code invariants (from the stabilization plan):

- authoritative run returns 0 **only** after a successful authoritative commit
- registry/schema invalid → non-zero (configuration failure)
- required step failed or blocked → non-zero (execution failure)
- execution succeeded but admission rejected → non-zero (admission failure)
- transaction rollback / recovery → non-zero (transaction failure)
- mandatory ledger/event sink failure → non-zero (mandatory-sink failure)

``exit_code`` is *derived* from the other fields in ``__post_init__`` so that
callers cannot accidentally supply a wrong value -- the constructor accepts an
``exit_code`` argument (for backward-compat / test convenience) but always
overwrites it with the computed value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Exit-code constants
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_CONFIGURATION_FAILURE = 2
EXIT_EXECUTION_FAILURE = 3
EXIT_ADMISSION_FAILURE = 4
EXIT_TRANSACTION_FAILURE = 5
EXIT_MANDATORY_SINK_FAILURE = 6

# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------

REASON_REQUIRED_STEP_FAILED = "REQUIRED_STEP_FAILED"
REASON_STEP_BLOCKED = "STEP_BLOCKED"
REASON_REGISTRY_INVALID = "REGISTRY_INVALID"
REASON_SCHEMA_INVALID = "SCHEMA_INVALID"
REASON_ADMISSION_REJECTED = "ADMISSION_REJECTED"
REASON_TRANSACTION_ROLLED_BACK = "TRANSACTION_ROLLED_BACK"
REASON_TRANSACTION_FAILED = "TRANSACTION_FAILED"
REASON_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
REASON_MANDATORY_SINK_FAILED = "MANDATORY_SINK_FAILED"
REASON_PUBLISH_NOT_COMMITTED = "PUBLISH_NOT_COMMITTED"
REASON_SCHEDULE_SLOT_ALREADY_CLAIMED = "SCHEDULE_SLOT_ALREADY_CLAIMED"
REASON_EARLY_RUN_FAILURE = "EARLY_RUN_FAILURE"

# ---------------------------------------------------------------------------
# Verdict constants
# ---------------------------------------------------------------------------

ADMISSION_PASS = "PASS"
ADMISSION_BLOCK = "BLOCK"

PUBLISH_COMMITTED = "COMMITTED"
PUBLISH_NOT_PUBLISHED = "NOT_PUBLISHED"
PUBLISH_ROLLED_BACK = "ROLLED_BACK"
PUBLISH_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

SPEC_OK = "OK"
SPEC_INVALID = "INVALID"

EXECUTION_SUCCESS = "SUCCESS"
EXECUTION_FAILED = "FAILED"
EXECUTION_BLOCKED = "BLOCKED"

AUTHORITY_AUTHORITATIVE = "authoritative"
AUTHORITY_DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class RunOutcome:
    """The single authoritative state object for a daily run.

    Fields:
        run_id: Unique run identifier.
        spec_status: Registry/schema validity (``OK`` or ``INVALID``).
        execution_status: Step execution outcome (``SUCCESS``, ``FAILED``, ``BLOCKED``).
        failed_steps: Step IDs that failed.
        blocked_steps: Step IDs blocked by upstream failure.
        degraded_steps: Step IDs that ran in degraded mode.
        admission_verdict: Publish admission verdict (``PASS`` or ``BLOCK``).
        publish_status: Transaction outcome (``COMMITTED``, ``NOT_PUBLISHED``,
            ``ROLLED_BACK``, ``RECOVERY_REQUIRED``).
        authority_mode: ``authoritative`` or ``diagnostic``.
        reason_codes: List of machine-readable reason codes.
        generation_id: Candidate or committed generation identity when present.
        release_id: Harvester release identity observed by the run.
        exit_code: Derived exit code (overwritten in ``__post_init__``).
    """

    run_id: str
    spec_status: str
    execution_status: str
    failed_steps: list[str] = field(default_factory=list)
    blocked_steps: list[str] = field(default_factory=list)
    degraded_steps: list[str] = field(default_factory=list)
    admission_verdict: str = ADMISSION_BLOCK
    publish_status: str = PUBLISH_NOT_PUBLISHED
    authority_mode: str = AUTHORITY_AUTHORITATIVE
    reason_codes: list[str] = field(default_factory=list)
    exit_code: int = EXIT_EXECUTION_FAILURE  # always overwritten in __post_init__
    generation_id: str | None = None
    release_id: str | None = None
    provider_status: str | None = None
    provider_cache_within_grace: bool | None = None

    def __post_init__(self) -> None:
        """Derive ``exit_code`` from the other fields, ignoring caller-supplied value."""
        object.__setattr__(self, "exit_code", self._compute_exit_code())

    def _compute_exit_code(self) -> int:
        """Return the exit code dictated by the run state.

        Evaluation order (most specific failure first):
        1. Spec invalid → configuration failure
        2. Mandatory sink failure → mandatory-sink failure
        3. Transaction rollback/recovery → transaction failure
        4. Required step failed or blocked → execution failure
        5. Admission rejected after successful execution → admission failure
        6. Publish not committed → execution/admission failure (depends on path)
        7. Otherwise → success (0)
        """
        codes = set(self.reason_codes)

        # 1. Configuration failure: registry/schema invalid
        if self.spec_status != SPEC_OK or REASON_REGISTRY_INVALID in codes or REASON_SCHEMA_INVALID in codes:
            return EXIT_CONFIGURATION_FAILURE

        # 2. Mandatory-sink failure
        if REASON_MANDATORY_SINK_FAILED in codes:
            return EXIT_MANDATORY_SINK_FAILURE

        # 3. Transaction failure
        if self.publish_status in (PUBLISH_ROLLED_BACK, PUBLISH_RECOVERY_REQUIRED) or (
            REASON_TRANSACTION_ROLLED_BACK in codes
            or REASON_TRANSACTION_FAILED in codes
            or REASON_RECOVERY_REQUIRED in codes
        ):
            return EXIT_TRANSACTION_FAILURE

        # A failure before admission/transaction evaluation must still use the
        # execution-failure code.  Otherwise the default BLOCK admission would
        # mask an initialization/configuration exception as an admission-only
        # rejection and make early exits diverge from the typed outcome.
        if REASON_EARLY_RUN_FAILURE in codes:
            return EXIT_EXECUTION_FAILURE

        # 4. Execution failure: required steps failed or blocked.  This must
        # precede admission rejection: a failed execution may also have a
        # default BLOCK admission, but it is still an execution failure rather
        # than a clean execution rejected by admission.
        if (
            self.execution_status != EXECUTION_SUCCESS
            or self.failed_steps
            or self.blocked_steps
            or REASON_REQUIRED_STEP_FAILED in codes
            or REASON_STEP_BLOCKED in codes
        ):
            return EXIT_EXECUTION_FAILURE

        # 5. Admission rejection after successful execution
        if self.admission_verdict == ADMISSION_BLOCK or REASON_ADMISSION_REJECTED in codes:
            return EXIT_ADMISSION_FAILURE

        # 6. Publish not committed despite no explicit failure
        if self.authority_mode == AUTHORITY_AUTHORITATIVE and self.publish_status != PUBLISH_COMMITTED:
            return EXIT_EXECUTION_FAILURE

        # 7. Success
        return EXIT_SUCCESS

    @property
    def operational_state(self) -> str:
        """Return the scheduler/readiness classification.

        FRESH_READY requires all three conditions:
        - exit_code == 0  (no failure of any kind)
        - authority_mode == "authoritative"  (not a diagnostic/dry-run)
        - publish_status == "COMMITTED"  (an authoritative generation was published)

        Diagnostic no-ops (duplicate schedule wake-up, dry-run) succeed
        without producing an authoritative generation and must not claim
        FRESH_READY.
        """
        if self.exit_code == EXIT_SUCCESS and (
            self.authority_mode != AUTHORITY_AUTHORITATIVE
            or self.publish_status != PUBLISH_COMMITTED
        ):
            return "NOOP_COMPLETED"
        if self.exit_code == EXIT_SUCCESS:
            return "FRESH_READY"
        if (
            self.execution_status == EXECUTION_SUCCESS
            and self.degraded_steps
            and self.provider_cache_within_grace is not False
            and not self.failed_steps
            and not self.blocked_steps
        ):
            return "COMPLETED_DEGRADED"
        if self.execution_status == EXECUTION_SUCCESS and not self.failed_steps and not self.blocked_steps:
            return "COMPLETED_BLOCKED"
        return "SYSTEM_FAILED"

    @property
    def status(self) -> str:
        """Return the only consumer-facing run status derived from ``exit_code``."""
        if self.operational_state == "COMPLETED_DEGRADED":
            return "degraded"
        if self.operational_state == "NOOP_COMPLETED":
            return "success"
        return "success" if self.exit_code == EXIT_SUCCESS else "partial_failure"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON / RunBundle / notification consumers."""
        return {
            "run_id": self.run_id,
            "spec_status": self.spec_status,
            "execution_status": self.execution_status,
            "failed_steps": list(self.failed_steps),
            "blocked_steps": list(self.blocked_steps),
            "degraded_steps": list(self.degraded_steps),
            "admission_verdict": self.admission_verdict,
            "publish_status": self.publish_status,
            "authority_mode": self.authority_mode,
            "reason_codes": list(self.reason_codes),
            "exit_code": self.exit_code,
            "status": self.status,
            "operational_state": self.operational_state,
            "generation_id": self.generation_id,
            "release_id": self.release_id,
            "provider_status": self.provider_status,
            "provider_cache_within_grace": self.provider_cache_within_grace,
        }
