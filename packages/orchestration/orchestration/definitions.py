"""Dagster Definitions for daily_job and refresh_current_job.

launchd / ``python -m orchestration.cli daily`` execute ``daily_job`` in-process.
"""
from __future__ import annotations

import json
import os

from dagster import Definitions, Failure, job, op

from orchestration.assets.boundary_pilot import BOUNDARY_ASSETS, BOUNDARY_CHECKS
from orchestration.assets.data_quality import DATA_QUALITY_CHECKS
from orchestration.assets.registry_block_checks import BLOCK_REGISTRY_ASSETS, BLOCK_REGISTRY_CHECKS
from orchestration.assets.registry_quality_checks import REGISTRY_QUALITY_CHECKS
from orchestration.assets.registry_shadow import SHADOW_REGISTRY_ASSETS
from orchestration.ops.refresh_chain import refresh_admission_op, refresh_producers_op
from orchestration.schedules import daily_schedule


@op(name="daily_job_entry")
def daily_job_entry(context):
    raw = os.environ.get("SYSTEM_DAGSTER_DAILY_ARGV", "")
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        decoded = None
    if isinstance(decoded, list) and all(isinstance(part, str) for part in decoded):
        argv = list(decoded)
    else:
        argv = [part for part in raw.split("\0") if part]
    context.log.info("daily_job starting via orchestration.daily_pipeline (argv=%s)", argv)
    from orchestration.daily_pipeline import run_scheduled_daily

    outcome = run_scheduled_daily(argv)
    if outcome.exit_code != 0:
        raise Failure(
            description=(
                f"daily run {outcome.run_id} failed with exit_code={outcome.exit_code}"
            ),
            metadata={
                "run_id": outcome.run_id,
                "exit_code": outcome.exit_code,
                "reason_codes": ",".join(outcome.reason_codes),
            },
        )
    context.log.info("daily_job finished: run_id=%s", outcome.run_id)


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
    assets=[*BOUNDARY_ASSETS, *SHADOW_REGISTRY_ASSETS, *BLOCK_REGISTRY_ASSETS],
    asset_checks=[*BOUNDARY_CHECKS, *DATA_QUALITY_CHECKS, *REGISTRY_QUALITY_CHECKS, *BLOCK_REGISTRY_CHECKS],
)
