"""Dagster Definitions for compatibility, refresh, and shadow surfaces.

The scheduled default is ``verity daily`` -> the generated plan job.  The
historical ``daily_job`` definition remains visible for migration inspection,
but is stopped and fails closed so it can never create a Dagster-inside-
Dagster execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from dagster import (
    AssetSelection,
    DefaultScheduleStatus,
    Definitions,
    Failure,
    ScheduleDefinition,
    define_asset_job,
    job,
    op,
)

from orchestration.assets.boundary_pilot import BOUNDARY_ASSETS, BOUNDARY_CHECKS
from orchestration.assets.data_quality import DATA_QUALITY_CHECKS
from orchestration.assets.native_batch import NATIVE_BATCH_ASSETS, NATIVE_BATCH_CHECKS
from orchestration.assets.native_core import NATIVE_CORE_ASSETS, NATIVE_CORE_CHECKS
from orchestration.assets.native_decision import (
    NATIVE_DECISION_ASSETS,
    NATIVE_DECISION_CHECKS,
)
from orchestration.assets.native_adjacent import (
    NATIVE_ADJACENT_ASSETS,
    NATIVE_ADJACENT_CHECKS,
)
from orchestration.assets.native_quality import (
    NATIVE_QUALITY_ASSETS,
    NATIVE_QUALITY_CHECKS,
)
from orchestration.assets.registry_block_checks import (
    BLOCK_REGISTRY_ASSETS,
    BLOCK_REGISTRY_CHECKS,
)
from orchestration.assets.registry_degrade_checks import (
    DEGRADE_REGISTRY_ASSETS,
    DEGRADE_REGISTRY_CHECKS,
)
from orchestration.assets.registry_quality_checks import REGISTRY_QUALITY_CHECKS
from orchestration.assets.registry_shadow import SHADOW_REGISTRY_ASSETS
from orchestration.native_daily import build_native_daily_assets
from orchestration.native_daily_checks import build_native_daily_checks
from orchestration.ops.refresh_chain import refresh_admission_op, refresh_producers_op
from orchestration.runner import DailyRunPayload
from orchestration.schedules import daily_schedule
from verity.runtime.runtime_io import ROOT
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import load_pipeline


_NATIVE_PILOT_KEYS = tuple(
    asset_def.key for asset_def in (*NATIVE_BATCH_ASSETS, *NATIVE_QUALITY_ASSETS)
)
native_pilot_job = define_asset_job(
    name="native_pilot_job",
    selection=AssetSelection.assets(*_NATIVE_PILOT_KEYS),
    description="Stopped Wave 4 Dagster-native pilot; never a publication authority.",
    tags={"authority": "shadow_only", "promotion_allowed": "false"},
)
native_pilot_schedule = ScheduleDefinition(
    name="native_pilot_schedule",
    cron_schedule="0 8 * * *",
    job_name="native_pilot_job",
    default_status=DefaultScheduleStatus.STOPPED,
    description="Stopped observation schedule for native-pilot assets; enable only after parity approval.",
)

_NATIVE_CORE_PILOT_KEYS = tuple(asset_def.key for asset_def in NATIVE_CORE_ASSETS)
native_core_pilot_job = define_asset_job(
    name="native_core_pilot_job",
    selection=AssetSelection.assets(*_NATIVE_CORE_PILOT_KEYS),
    description=(
        "Stopped Wave 4 core-boundary Dagster pilot; blocking checks apply "
        "only inside this shadow graph."
    ),
    tags={"authority": "shadow_only", "promotion_allowed": "false"},
)
native_core_pilot_schedule = ScheduleDefinition(
    name="native_core_pilot_schedule",
    cron_schedule="15 8 * * *",
    job_name="native_core_pilot_job",
    default_status=DefaultScheduleStatus.STOPPED,
    description=(
        "Stopped observation schedule for core writer boundaries; enable "
        "only after an approved dual-run window."
    ),
)

_NATIVE_DECISION_PILOT_KEYS = tuple(
    asset_def.key for asset_def in NATIVE_DECISION_ASSETS
)
native_decision_pilot_job = define_asset_job(
    name="native_decision_pilot_job",
    selection=AssetSelection.assets(*_NATIVE_DECISION_PILOT_KEYS),
    description=(
        "Stopped Wave 4 judgment-to-risk Dagster pilot; blocking artifact "
        "checks apply only inside this shadow graph."
    ),
    tags={"authority": "shadow_only", "promotion_allowed": "false"},
)
native_decision_pilot_schedule = ScheduleDefinition(
    name="native_decision_pilot_schedule",
    cron_schedule="30 8 * * *",
    job_name="native_decision_pilot_job",
    default_status=DefaultScheduleStatus.STOPPED,
    description=(
        "Stopped observation schedule for judgment, promotion, trade, and "
        "risk boundaries; enable only after approved dual-run evidence."
    ),
)

_NATIVE_ADJACENT_PILOT_KEYS = tuple(
    asset_def.key for asset_def in NATIVE_ADJACENT_ASSETS
)
native_adjacent_pilot_job = define_asset_job(
    name="native_adjacent_pilot_job",
    selection=AssetSelection.assets(*_NATIVE_ADJACENT_PILOT_KEYS),
    description=(
        "Stopped Wave 4 ledger and paper-position Dagster pilot; it writes "
        "only a health generation seeded from accepted read-only state."
    ),
    tags={"authority": "shadow_only", "promotion_allowed": "false"},
)
native_adjacent_pilot_schedule = ScheduleDefinition(
    name="native_adjacent_pilot_schedule",
    cron_schedule="45 8 * * *",
    job_name="native_adjacent_pilot_job",
    default_status=DefaultScheduleStatus.STOPPED,
    description=(
        "Stopped observation schedule for decision ledger and paper position "
        "boundaries; enable only after approved adjacent parity evidence."
    ),
)


def _native_daily_shadow_run_step(*_args, **_kwargs):
    raise AssertionError("native_daily_shadow_job attempted business execution")


_NATIVE_DAILY_SHADOW_PLAN = load_pipeline(WorkspacePaths(root=ROOT))
_NATIVE_DAILY_SHADOW_PAYLOAD = DailyRunPayload(
    args=SimpleNamespace(
        force_weekly=True,
        skip_harvester=False,
        skip_etf=False,
    ),
    start_time=datetime.now(UTC),
    total_steps=len(_NATIVE_DAILY_SHADOW_PLAN.sequence()),
    run_step_fn=_native_daily_shadow_run_step,
    record_fn=lambda _result, input_artifacts=None: None,
    benchmark_panel_path=(
        ROOT
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "data"
        / "benchmark_panel.parquet"
    ),
    run_id="native-daily-shadow-definition",
    plan=_NATIVE_DAILY_SHADOW_PLAN,
    dry_run=True,
)
NATIVE_DAILY_SHADOW_ASSETS = build_native_daily_assets(
    _NATIVE_DAILY_SHADOW_PAYLOAD,
    plan=_NATIVE_DAILY_SHADOW_PLAN,
)
NATIVE_DAILY_SHADOW_CHECKS = build_native_daily_checks(
    NATIVE_DAILY_SHADOW_ASSETS,
    blocking=False,
)
_NATIVE_DAILY_SHADOW_KEYS = tuple(
    asset_def.key for asset_def in NATIVE_DAILY_SHADOW_ASSETS
)
native_daily_shadow_job = define_asset_job(
    name="native_daily_shadow_job",
    selection=AssetSelection.assets(*_NATIVE_DAILY_SHADOW_KEYS),
    description=(
        "Stopped full-plan Dagster-native dry-run graph; it resolves the real "
        "CompiledPlan without executing business steps."
    ),
    tags={"authority": "shadow_only", "promotion_allowed": "false", "dry_run": "true"},
)
native_daily_shadow_schedule = ScheduleDefinition(
    name="native_daily_shadow_schedule",
    cron_schedule="30 8 * * *",
    job_name="native_daily_shadow_job",
    default_status=DefaultScheduleStatus.STOPPED,
    description=(
        "Stopped full-plan structural observation schedule; enable only for "
        "explicit migration evidence collection."
    ),
)


@op(name="daily_job_entry")
def daily_job_entry(context):
    del context
    raise Failure(
        description=(
            "legacy outer daily_job is disabled; use the single execution "
            "spine through `verity daily`"
        ),
        metadata={
            "canonical_entrypoint": "verity.cli.daily_run:run_daily",
            "execution_mode": "dagster_generated_plan_job",
            "reason": "nested_dagster_execution_forbidden",
        },
    )


@job(
    name="daily_job",
    description=(
        "Stopped compatibility sentinel. The scheduled default is the "
        "generated-plan job invoked by `verity daily`."
    ),
)
def daily_job():
    daily_job_entry()


@job(name="refresh_current_job", description="Operator refresh of Output/current.")
def refresh_current_job():
    admission = refresh_admission_op()
    refresh_producers_op(admission)


defs = Definitions(
    jobs=[
        daily_job,
        refresh_current_job,
        native_pilot_job,
        native_core_pilot_job,
        native_decision_pilot_job,
        native_adjacent_pilot_job,
        native_daily_shadow_job,
    ],
    schedules=[
        daily_schedule,
        native_pilot_schedule,
        native_core_pilot_schedule,
        native_decision_pilot_schedule,
        native_adjacent_pilot_schedule,
        native_daily_shadow_schedule,
    ],
    assets=[
        *BOUNDARY_ASSETS,
        *NATIVE_BATCH_ASSETS,
        *NATIVE_CORE_ASSETS,
        *NATIVE_DECISION_ASSETS,
        *NATIVE_ADJACENT_ASSETS,
        *NATIVE_QUALITY_ASSETS,
        *NATIVE_DAILY_SHADOW_ASSETS,
        *SHADOW_REGISTRY_ASSETS,
        *BLOCK_REGISTRY_ASSETS,
        *DEGRADE_REGISTRY_ASSETS,
    ],
    asset_checks=[
        *BOUNDARY_CHECKS,
        *DATA_QUALITY_CHECKS,
        *NATIVE_BATCH_CHECKS,
        *NATIVE_CORE_CHECKS,
        *NATIVE_DECISION_CHECKS,
        *NATIVE_ADJACENT_CHECKS,
        *NATIVE_QUALITY_CHECKS,
        *REGISTRY_QUALITY_CHECKS,
        *BLOCK_REGISTRY_CHECKS,
        *DEGRADE_REGISTRY_CHECKS,
        *NATIVE_DAILY_SHADOW_CHECKS,
    ],
)
