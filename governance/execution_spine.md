# Step 2 — One Execution Spine

The scheduled default is now one Python-owned spine:

```text
launchd scheduler
  -> scripts/run_daily_scheduled.sh
  -> scripts/run_dagster_daily.sh
  -> verity daily
  -> orchestration.daily_pipeline.run_scheduled_daily
  -> verity.cli.daily_run.run_daily
  -> compiled_runtime_plan.json
  -> daily_compiled_plan_job (one Dagster execution)
  -> domain callables / explicitly justified process boundaries
  -> publication transaction
  -> RunOutcome
```

The shell files are process adapters. They set the runtime environment, apply
resource limits, perform the dependency-availability check, and `exec` the
Python entrypoint. Retry policy, generation reconciliation, legacy selection,
step composition, publication, and authority decisions are Python concerns.

The authoring source is split by concern under `governance/pipeline/`:
topology, execution profiles, monitoring, freshness, ownership, and schedule
metadata. `system_runtime.registry_authoring` merges and validates those files
once; `system_runtime.pipeline` then produces the one `CompiledPipeline` and
writes `compiled_runtime_plan.json` into each run bundle. The historical
`governance/daily_pipeline_registry.yaml` is a `DERIVED` compatibility view,
not a runtime input. The artifact contains the plan/source identity, canonical
entrypoint, generated-plan mode, step DAG, timeouts, failure policy, artifact
contracts, and the logical topology/execution/monitoring/freshness/ownership/
schedule views. The Dagster graph receives this compiled object; it does not
re-read any YAML source.

The historical `daily_job` is retained as a stopped fail-closed sentinel. It
cannot call the scheduled pipeline because doing so would recreate Dagster
inside Dagster. Native assets remain stopped shadow definitions until their
promotion gate is explicitly approved. `SYSTEM_USE_LEGACY_DAILY_RUN=1` is an
explicit emergency compatibility path and is not part of the scheduled
default.

Machine-readable gate evidence is recorded in
`governance/step2_execution_spine.yaml`; the bounded real-path closure record is
`governance/step2_closure_audit.md`. Provider admission and reliability remain
separate gates.
