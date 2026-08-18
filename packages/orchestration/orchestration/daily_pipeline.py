"""Full daily pipeline invocation for the Dagster ``daily_job`` op."""
from __future__ import annotations

import logging
import os
from typing import Sequence, cast

from system_runtime.run_outcome import EXIT_MANDATORY_SINK_FAILURE, RunOutcome

logger = logging.getLogger(__name__)


def run_scheduled_daily(argv: Sequence[str] | None = None) -> RunOutcome:
    """Run the full scheduled batch (bundle + sequence + publish).

    Invoked by Dagster ``daily_job``. Uses ``scripts.daily_run.run_daily`` so
    launchd -> Dagster -> pipeline is one authority path.

    Returns the authoritative :class:`RunOutcome`. The Dagster op turns a
    non-zero outcome into a failed run; the CLI reads the same exit code.
    """
    import sys
    from pathlib import Path

    # Prevent nested ``python -m orchestration.cli daily`` re-entry.
    os.environ["SYSTEM_INSIDE_DAGSTER_DAILY_JOB"] = "1"
    root = Path(__file__).resolve().parents[3]
    for extra in (str(root), str(root / "scripts"), str(root / "packages" / "orchestration")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    from scripts import daily_run as daily_run_mod

    args = daily_run_mod.parse_args(list(argv) if argv is not None else None)
    try:
        outcome = cast(RunOutcome, daily_run_mod.run_daily(args))
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
                stage="dagster_daily_run_initialization",
            ),
        )
    # Propagate via env so cmd_daily can read it after execute_in_process.
    os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(outcome.exit_code)
    return outcome
