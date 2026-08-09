# Orchestration Context

Dagster owns the default-path daily and refresh orchestration. Registry YAML
remains the authority for step order, schedules, and failure behavior.

## Owns

- `packages/orchestration/` Dagster definitions, ops, quality adapters, DVC helpers
- in-process cutover for `scripts/daily_run.py` and `scripts/refresh_output_current.py`
- Pandera content-clock evaluation (GE-shaped artifacts; optional GE pip extra)
- DVC pointer recording for Harvester releases and snapshot promotes
- Optional operator observability via `system_runtime/observability.py` (Sentry DSN /
  Datadog `DD_API_KEY`), fanned out from `scripts/_notify.py`

## Primary Paths

- `packages/orchestration/orchestration/`
- `governance/daily_pipeline_registry.yaml`
- `configs/great_expectations/expectations/` (suite contract docs)
- `configs/dvc/config` (local no-scm DVC remote template)
- `scripts/daily_run.py`
- `scripts/refresh_output_current.py`
- `scripts/archive/_legacy_daily_run_executor.py` (emergency only)

## Escape hatch

`SYSTEM_USE_LEGACY_DAILY_RUN=1` bypasses Dagster and uses
`scripts/archive/_legacy_daily_run_executor.py` (archived; not on the default path).

## Launchd

`com.system.daily-run` → `run_daily_scheduled.sh` → `run_dagster_daily.sh` →
`orchestrate.sh daily` → `python -m orchestration.cli daily` → Dagster `daily_job`.

## Do not

- Duplicate step lists in Python
- Import claim-ladder / Learning Hub semantics into Dagster graphs
- Replace `Output/current` atomic publish with DVC (display layer stays custom)
- Import `scripts/archive/_legacy_daily_run_executor` outside the escape hatch
