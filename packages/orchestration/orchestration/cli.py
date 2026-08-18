"""CLI entry for launchd / operators: run Dagster jobs in-process."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import cast

from system_runtime.run_outcome import EXIT_MANDATORY_SINK_FAILURE


def _ensure_workspace_path() -> None:
    root = os.environ.get("SYSTEM_ROOT") or os.environ.get("SYSTEM_WORKSPACE_ROOT")
    if root and root not in sys.path:
        sys.path.insert(0, root)
    pkg = os.path.join(
        root or os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "packages",
        "orchestration",
    )
    if pkg not in sys.path:
        sys.path.insert(0, pkg)


def cmd_daily(argv: list[str]) -> int:
    """Execute ``daily_job`` in-process (launchd default path).

    Returns the authoritative exit code from :class:`RunOutcome` (propagated
    via ``SYSTEM_DAILY_EXIT_CODE``), falling back to Dagster op success only
    if the env var was not set (e.g. an early crash before run_daily).
    """
    _ensure_workspace_path()
    # launchd does not inherit an interactive shell's environment.  Load only
    # the allowlisted provider keys from the user-owned, mode-600 secret file;
    # explicit environment variables remain authoritative.
    from orchestration.provider_secrets import load_provider_secrets

    load_provider_secrets()
    # Forward CLI flags to daily_run via env for the job op to consume.
    # Environment values cannot contain NUL bytes.  JSON preserves argument
    # boundaries safely; definitions.py still accepts the historical NUL form
    # for callers that set the bridge variable directly.
    os.environ["SYSTEM_DAGSTER_DAILY_ARGV"] = json.dumps(argv, ensure_ascii=False)
    os.environ["SYSTEM_ORCHESTRATOR"] = "dagster"
    # Clear stale exit code from a previous invocation in the same process.
    os.environ.pop("SYSTEM_DAILY_EXIT_CODE", None)
    os.environ.pop("SYSTEM_DAILY_OUTCOME_READY", None)
    os.environ.pop("SYSTEM_DAILY_SINKS_COMPLETE", None)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_DIR", None)
    os.environ.pop("SYSTEM_DAILY_BUNDLE_RUN_ID", None)
    from orchestration.definitions import daily_job

    try:
        result = daily_job.execute_in_process()
    except Exception:
        # Dagster must fail visibly, while the process still returns the exact
        # typed RunOutcome code produced by the same run.
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
        from scripts import daily_run as daily_run_mod

        early_args = daily_run_mod.parse_args(argv)
        outcome = daily_run_mod.build_early_failure_outcome(
            early_args,
            sys.exc_info()[1] or RuntimeError("unknown dagster failure"),
            stage="dagster_job_entry",
        )
        return int(outcome.exit_code)
    env_exit = os.environ.get("SYSTEM_DAILY_EXIT_CODE")
    if env_exit is not None:
        try:
            return int(env_exit)
        except ValueError:
            return 1
    return 0 if bool(result.success) else 1


def cmd_refresh(argv: list[str]) -> int:
    _ensure_workspace_path()
    os.environ["SYSTEM_DAGSTER_REFRESH_ARGV"] = "\0".join(argv)
    os.environ["SYSTEM_ORCHESTRATOR"] = "dagster"
    from orchestration.runner import run_refresh_via_dagster

    skip = "--skip-measurement" in argv
    dry = "--dry-run" in argv
    return cast(int, run_refresh_via_dagster(skip_measurement=skip, dry_run=dry))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestration")
    sub = parser.add_subparsers(dest="command", required=True)
    daily = sub.add_parser("daily", help="Run Dagster daily_job (launchd entry)")
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
