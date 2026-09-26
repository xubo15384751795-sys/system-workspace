"""CLI entry for launchd / operators: run Dagster jobs in-process."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import cast

from system_runtime.run_outcome import EXIT_MANDATORY_SINK_FAILURE
from system_runtime.context import RuntimeContext


def cmd_daily(
    argv: list[str],
    *,
    runtime_context: RuntimeContext | None = None,
) -> int:
    """Execute the one scheduled execution spine.

    The CLI is an adapter only.  It prepares process-level runtime state and
    calls the canonical Python entrypoint, which compiles the runtime plan and
    owns the single generated-plan Dagster execution.  There is deliberately
    no outer Dagster job execution here.
    """
    # Resolve the canonical logical secret through RuntimeContext.  The host
    # implementation may be environment, a mode-600 file, systemd's
    # EnvironmentFile, or another SecretProvider; downstream providers only
    # see FRED_API_KEY and never the OPENBB compatibility alias.
    context = runtime_context or RuntimeContext.current_context()
    fred_key = context.secrets.get("FRED_API_KEY")
    if fred_key:
        os.environ["FRED_API_KEY"] = fred_key
    os.environ.pop("OPENBB_FRED_API_KEY", None)
    from system_runtime.observability import init_sentry
    from system_runtime.runtime_secrets import load_runtime_secrets

    load_runtime_secrets()
    try:
        init_sentry()
    except Exception:  # noqa: BLE001 - observability must not block the pipeline
        import logging

        logging.getLogger(__name__).debug("Sentry initialization unavailable", exc_info=True)
    # Keep this bridge for explicitly inspected compatibility definitions; the
    # default path below does not ask definitions.daily_job to consume it.
    os.environ["SYSTEM_DAGSTER_DAILY_ARGV"] = json.dumps(argv, ensure_ascii=False)
    os.environ["SYSTEM_ORCHESTRATOR"] = "dagster"
    # Clear stale exit code from a previous invocation in the same process.
    os.environ.pop("SYSTEM_DAILY_EXIT_CODE", None)
    os.environ.pop("SYSTEM_DAILY_OUTCOME_READY", None)
    os.environ.pop("SYSTEM_DAILY_SINKS_COMPLETE", None)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_DIR", None)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_RUN_ID", None)
    try:
        from orchestration.daily_pipeline import run_scheduled_daily

        if runtime_context is None:
            outcome = run_scheduled_daily(argv)
        else:
            outcome = run_scheduled_daily(argv, runtime_context=runtime_context)
    except Exception:
        if (
            os.environ.get("SYSTEM_DAILY_OUTCOME_READY") == "1"
            and os.environ.get("SYSTEM_DAILY_SINKS_COMPLETE") != "1"
        ):
            os.environ["SYSTEM_DAILY_EXIT_CODE"] = str(EXIT_MANDATORY_SINK_FAILURE)
            return int(EXIT_MANDATORY_SINK_FAILURE)
        env_exit = os.environ.get("SYSTEM_DAILY_EXIT_CODE")
        if env_exit is not None:
            try:
                return int(env_exit)
            except ValueError:
                return 1
        # Cover failures before the Dagster op could call the shared daily
        # pipeline wrapper.  Materialize the same typed early-failure result
        # used by the direct daily_run entrypoint.
        from verity.cli import daily_run as daily_run_mod

        early_args = daily_run_mod.parse_args(argv)
        outcome = daily_run_mod.build_early_failure_outcome(
            early_args,
            sys.exc_info()[1] or RuntimeError("unknown dagster failure"),
            stage="execution_spine_entry",
        )
        return int(outcome.exit_code)
    return int(outcome.exit_code)


def cmd_refresh(argv: list[str]) -> int:
    os.environ["SYSTEM_DAGSTER_REFRESH_ARGV"] = "\0".join(argv)
    os.environ["SYSTEM_ORCHESTRATOR"] = "dagster"
    from orchestration.runner import run_refresh_via_dagster

    skip = "--skip-measurement" in argv
    dry = "--dry-run" in argv
    return cast(int, run_refresh_via_dagster(skip_measurement=skip, dry_run=dry))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestration")
    sub = parser.add_subparsers(dest="command", required=True)
    daily = sub.add_parser(
        "daily", help="Run the single generated-plan Dagster execution (launchd entry)"
    )
    daily.add_argument("job_args", nargs=argparse.REMAINDER)
    refresh = sub.add_parser("refresh", help="Run Dagster refresh_current_job")
    refresh.add_argument("job_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "daily":
        # REMAINDER may include a leading "--"
        job_args = list(args.job_args)
        if job_args and job_args[0] == "--":
            job_args = job_args[1:]
        return cmd_daily(job_args)
    if args.command == "refresh":
        job_args = list(args.job_args)
        if job_args and job_args[0] == "--":
            job_args = job_args[1:]
        return cmd_refresh(job_args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
