"""Canonical scheduled invocation for the single daily execution spine."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Sequence, cast

from system_runtime.publish_transaction import PublishTransaction
from system_runtime.context import RuntimeContext
from system_runtime.run_outcome import EXIT_MANDATORY_SINK_FAILURE, RunOutcome
from verity.runtime.runtime_io import ROOT

logger = logging.getLogger(__name__)


def _reconcile_generation_before_run(args: object) -> None:
    """Apply the fail-closed generation preflight in Python, not shell."""
    if bool(getattr(args, "dry_run", False)):
        return
    raw_output_root = getattr(args, "output_root", None)
    output_root = Path(raw_output_root).expanduser().resolve() if raw_output_root else None
    state = PublishTransaction.reconcile(ROOT, output_root=output_root)
    logger.info("generation preflight: status=%s", state.get("status"))
    if state.get("status") == "recovery_required":
        raise RuntimeError(
            "generation reconciliation requires operator recovery before the scheduled run"
        )


def run_scheduled_daily(
    argv: Sequence[str] | None = None,
    *,
    runtime_context: RuntimeContext | None = None,
) -> RunOutcome:
    """Run the full scheduled batch (bundle + sequence + publish).

    This is the canonical Python entrypoint for ``scheduler -> verity daily``.
    It performs the runtime preflight and then invokes ``run_daily`` exactly
    once; ``run_daily`` owns the one generated-plan Dagster execution.

    Returns the authoritative :class:`RunOutcome`. The Dagster op turns a
    non-zero outcome into a failed run; the CLI reads the same exit code.
    """
    from verity.cli import daily_run as daily_run_mod

    args = daily_run_mod.parse_args(list(argv) if argv is not None else None)
    try:
        _reconcile_generation_before_run(args)
        if runtime_context is None:
            raw_outcome = daily_run_mod.run_daily(args)
        else:
            raw_outcome = daily_run_mod.run_daily(args, runtime_context=runtime_context)
        outcome = cast(RunOutcome, raw_outcome)
    except Exception as exc:
        if (
            os.environ.get("SYSTEM_DAILY_OUTCOME_READY") == "1"
            and os.environ.get("SYSTEM_DAILY_SINKS_COMPLETE") != "1"
        ):
            # Preserve the mandatory-sink boundary.  The CLI sees the same
            # marker and returns exit 6 instead of relabeling a late failure
            # as an initialization failure.
            os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(EXIT_MANDATORY_SINK_FAILURE)
            raise
        outcome = cast(
            RunOutcome,
            daily_run_mod.build_early_failure_outcome(
                args,
                exc,
                stage="execution_spine_initialization",
            ),
        )
    # Propagate via env so cmd_daily can read it after execute_in_process.
    os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(outcome.exit_code)
    return outcome
