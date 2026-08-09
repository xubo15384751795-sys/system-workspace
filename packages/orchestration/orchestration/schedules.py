"""Dagster schedules mirroring launchd daily-run timing (07:00 local)."""
from __future__ import annotations

from dagster import DefaultScheduleStatus, ScheduleDefinition

daily_schedule = ScheduleDefinition(
    name="daily_run_0700",
    cron_schedule="0 7 * * *",
    job_name="daily_job",
    default_status=DefaultScheduleStatus.STOPPED,
    description="Mirrors com.system.daily-run launchd (07:00). Enable in Dagster UI when replacing launchd.",
)
