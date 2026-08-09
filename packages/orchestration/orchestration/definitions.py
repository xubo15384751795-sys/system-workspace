"""Dagster Definitions for daily_job and refresh_current_job.

launchd / ``python -m orchestration.cli daily`` execute ``daily_job`` in-process.
"""
from __future__ import annotations

import os

from dagster import Definitions, job, op

from orchestration.ops.refresh_chain import refresh_admission_op, refresh_producers_op
from orchestration.schedules import daily_schedule


@op(name="daily_job_entry")
def daily_job_entry(context):
    raw = os.environ.get("SYSTEM_DAGSTER_DAILY_ARGV", "")
    argv = [part for part in raw.split("\0") if part]
    context.log.info("daily_job starting via orchestration.daily_pipeline (argv=%s)", argv)
    from orchestration.daily_pipeline import run_scheduled_daily

    run_scheduled_daily(argv)
    context.log.info("daily_job finished")


@job(name="daily_job", description="Registry-driven scheduled batch (launchd / Dagster default path).")
def daily_job():
    daily_job_entry()


@job(name="refresh_current_job", description="Operator refresh of Output/current.")
def refresh_current_job():
    admission = refresh_admission_op()
    refresh_producers_op(admission)


defs = Definitions(
    jobs=[daily_job, refresh_current_job],
    schedules=[daily_schedule],
)
