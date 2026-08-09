"""CLI entry for launchd / operators: run Dagster jobs in-process."""
from __future__ import annotations

import argparse
import os
import sys


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
    """Execute ``daily_job`` in-process (launchd default path)."""
    _ensure_workspace_path()
    # Forward CLI flags to daily_run via env for the job op to consume.
    os.environ["SYSTEM_DAGSTER_DAILY_ARGV"] = "\0".join(argv)
    os.environ["SYSTEM_ORCHESTRATOR"] = "dagster"
    from orchestration.definitions import daily_job

    result = daily_job.execute_in_process()
    return 0 if result.success else 1


def cmd_refresh(argv: list[str]) -> int:
    _ensure_workspace_path()
    os.environ["SYSTEM_DAGSTER_REFRESH_ARGV"] = "\0".join(argv)
    os.environ["SYSTEM_ORCHESTRATOR"] = "dagster"
    from orchestration.runner import run_refresh_via_dagster

    skip = "--skip-measurement" in argv
    dry = "--dry-run" in argv
    return run_refresh_via_dagster(skip_measurement=skip, dry_run=dry)


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
