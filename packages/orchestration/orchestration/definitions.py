"""Dagster Definitions for daily_job and refresh_current_job.

Runtime cutover uses ``orchestration.runner`` (in-process ops).
These job graphs exist for Dagster UI / schedule attachment and dry discovery.
"""
from __future__ import annotations

from dagster import Definitions, job, op

from orchestration.ops.refresh_chain import refresh_admission_op, refresh_producers_op
from orchestration.schedules import daily_schedule


@op(name="daily_job_entry")
def daily_job_entry(context):
    context.log.info(
        "daily_job: execute via scripts/daily_run.py "
        "(orchestration.runner.run_daily_sequence_via_dagster)"
    )


@job(name="daily_job", description="Registry-driven scheduled batch (replaces custom daily_run loop).")
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
