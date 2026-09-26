# Step 2 Closure Audit

审计对象：`daily_pipeline_20260912_033951_2d0023`

审计边界：本审计只验收 execution spine。此次 `RunOutcome.exit_code=3` 是
Harvester provider/preflight failure 沿默认 spine 的 fail-closed 结果，不计为
Step 2 architecture failure。provider credential、LaunchAgent reconciliation 和
14-day reliability window 属于独立 gate，本审计不启动、不修改，也不把它们计入
Step 2 PASS/FAIL。

## 1. 实际 runtime call chain

```text
launchd / SYSTEM_RUN_ORIGIN=launchd
  -> scripts/run_daily_scheduled.sh
  -> scripts/run_dagster_daily.sh
  -> python -m verity.cli daily
  -> system_cli.app:daily
  -> orchestration.cli:cmd_daily
  -> orchestration.daily_pipeline:run_scheduled_daily
  -> verity.cli.daily_run:run_daily
  -> compile_runtime_plan + write compiled_runtime_plan.json
  -> orchestration.runner:run_daily_sequence_via_dagster
  -> build_daily_step_job
  -> daily_compiled_plan_job.execute_in_process()  [one boundary]
  -> 67 compiled plan steps (+ one graph summary op)
  -> return step results to run_daily
  -> admission calculation
  -> publication transaction / current-pointer decision
  -> RunOutcome
  -> bundle/event/alert/notification/observability sinks
  -> canonical Learning Hub bundle ingest and ledger closeout
  -> cmd_daily returns RunOutcome.exit_code
```

Source anchors:

- `scripts/run_daily_scheduled.sh:18-30` and `scripts/run_dagster_daily.sh:17-25`
  are process adapters and `exec` into the canonical CLI.
- `verity/cli/_application.py` routes `daily` to `orchestration.cli.cmd_daily`.
- `packages/orchestration/orchestration/cli.py:13-76` calls the Python spine and
  returns the same typed outcome code; it does not execute an outer Dagster job.
- `packages/orchestration/orchestration/daily_pipeline.py:30-65` calls
  `verity.cli.daily_run.run_daily` once.
- `verity/cli/daily_run.py:1064-1081` invokes the generated-plan runner once;
  publication/admission and `RunOutcome` follow at `verity/cli/daily_run.py:1096-1369`.

## 2. Dagster boundary inventory

### Default scheduled path

There is one active construction/execution pair:

| kind | source | result |
|---|---|---|
| graph construction | `packages/orchestration/orchestration/runner.py:130-314` | one graph generated from the compiled plan |
| job construction | `packages/orchestration/orchestration/runner.py:316-319` | `daily_compiled_plan_job` |
| execution invocation | `packages/orchestration/orchestration/runner.py:322-376` | exactly one `job.execute_in_process()` |
| nested guard | `packages/orchestration/orchestration/runner.py:324-328` | active marker rejects a second Dagster boundary |

The default path does not resolve or invoke `definitions.daily_job`. The registered
`daily_job` is a stopped fail-closed compatibility sentinel at
`packages/orchestration/orchestration/definitions.py:206-230`; its only behavior is
to raise `nested_dagster_execution_forbidden`. Native asset materialization is
opt-in through `SYSTEM_USE_NATIVE_DAILY_ASSETS` and is not enabled by the scheduled
default (`packages/orchestration/orchestration/native_daily.py:53-65,319-343`).
`Definitions(...)` at `packages/orchestration/orchestration/definitions.py:239-278`
only registers the stopped compatibility/shadow surfaces; registration is not an
execution invocation on the scheduled path.

### Non-default Dagster surfaces found in source

The repository still contains Dagster boundaries for explicitly invoked shadow/pilot
operators. They are not part of this run's default path and their registry entries
forbid `daily_pipeline` use (`governance/entrypoint_registry.yaml:150-162,199-245`):

- `run_native_core_shadow.py:99` — stopped core shadow job;
- `run_native_decision_shadow.py:80` — stopped decision shadow job;
- `run_native_adjacent_shadow.py:74` — stopped adjacent shadow job;
- `run_native_batch_shadow_parity.py:257,275` — parity-only materialization;
- `run_native_daily_plan_shadow.py:126-136` — dry parity materialization followed
  by an explicit generated-plan comparison run.

These are remaining migration debt and are intentionally excluded from the default
scheduled boundary. They do not provide evidence that this run entered Dagster
inside Dagster.

Runtime evidence for the target run:

- `Output/runs/daily_pipeline_20260912_033951_2d0023/compiled_runtime_plan.json`
  records `execution_mode=dagster_generated_plan_job`.
- `Output/state/runtime_events/run_events_2026-09-12.jsonl` contains one
  `daily_run_completed` event from `producer=daily_run`; its step records contain
  no Dagster job invocation or nested execution marker.
- The live run terminal output showed one `daily_compiled_plan_job` execution with
  one `RUN_START`, the generated graph steps, one `ENGINE_EVENT`, and one
  `RUN_SUCCESS`; no second Dagster run and no nested `execute_in_process()` appeared.

Conclusion: the target real run and the default scheduled source path have one
Dagster execution boundary. This is not a claim that every manually invoked shadow
operator in the repository has been removed.

## 3. Legacy daily executor

Not entered.

- The real invocation explicitly removed `SYSTEM_USE_LEGACY_DAILY_RUN` and
  `DAILY_RUN_EXECUTION_MODE` from the wrapper environment.
- `use_legacy_daily_run()` is false unless the opt-in environment variable is a
  truthy value (`verity/cli/daily_run.py:137-144`).
- The default branch selected `run_daily_sequence_via_dagster` at
  `verity/cli/daily_run.py:1044-1081`.
- The runtime bundle/event was produced by `daily_run`; no `daily_job_entry`,
  archived executor, or legacy executor step was recorded.

## 4. Compiled-plan subprocess inventory

The compiled plan contains exactly three `execution_mode=subprocess` steps. The
target run actually executed only `harvester`; `regime_detection` was blocked by
`harvester`, and the weekly overlay step was not executed in this run.

| step | plan command | required process isolation | compatibility debt | future migration candidate |
|---|---|---|---|---|
| `harvester` | `python -m harvester daily-release` | Yes for the current provider/resource and acquisition boundary | Yes; current process boundary is still a transition seam | Move to a callable boundary only after explicit resource, timeout, provenance and failure-parity evidence; canonical callable is `harvester.cli:main` |
| `regime_detection` | `Workbench ml.regime_detector.detect_regime(...)` | Current plan says `real_process_isolation`; not intrinsically required by the domain | Yes; this is an inline process compatibility boundary | Migrate to `ml.regime_detector:detect_regime` after output/provenance/resource parity |
| `build_overlay_shadow_report` | `python scripts/archive/build_overlay_shadow_report.py` | Yes while the archived executable is retained | High; explicitly `archive_legacy_executable` and weekly/shadow-only | Retire or wrap as an archive-owned callable after shadow evidence; do not promote into the core path |

The run event confirms the only executed subprocess was:

```text
harvester: mode=subprocess, status=failed, returncode=1,
subprocess_justification=real_process_isolation
```

The missing FRED credential is the cause of that provider/preflight failure; it is
not evidence of a second execution boundary.

## 5. One-spine failure propagation

The same spine produced all three layers of failure state:

1. The generated plan returned `harvester=failed`; downstream plan steps were
   represented as `blocked_upstream` rather than launching another coordinator.
2. `run_daily` converted those step results into
   `execution_status=FAILED`, `admission_verdict=BLOCK`, and
   `publish_status=NOT_PUBLISHED` (`verity/cli/daily_run.py:1336-1369`).
3. The same typed `RunOutcome` was written to the bundle, runtime event, alert,
   notification and observability sinks. The target artifacts report
   `FAILED / BLOCK / NOT_PUBLISHED / exit_code=3`:

   - `Output/runs/daily_pipeline_20260912_033951_2d0023/run_outcome.json`
   - `Output/runs/daily_pipeline_20260912_033951_2d0023/manifest.json`
   - `Output/runs/daily_pipeline_20260912_033951_2d0023/publish_candidate/admission.json`

The admission artifact also has `can_publish=false` and
`allows_decision_consumers=false`; therefore provider failure did not silently
become usable authority.

## 6. Post-outcome canonical import and mandatory sink audit

Status: PASS.

- The post-outcome bundle ingest imports
  `system_learning.operators.ingest_daily_run_to_hub` directly at
  `verity/cli/daily_run.py:1500-1509`; the old top-level shim import is absent.
- Bundle ingest and Learning Hub ledger closeout are one mandatory-sink boundary;
  there is no second Dagster job or scheduler side path (`verity/cli/daily_run.py:1499-1522`).
- On sink success, the function reaches the normal terminal return and does not
  change admission, publication, authority or the primary reason codes.
- On sink failure, `mandatory_outcome` copies the primary execution, failed,
  blocked, degraded, admission, publication, authority, generation, release and
  provider fields and appends only `MANDATORY_SINK_FAILED`
  (`verity/cli/daily_run.py:1523-1539`). It rewrites the same bundle identity,
  event, alert, notification and observability evidence, then returns exit code 6.
- Thus a mandatory sink cannot overwrite the primary failure; sink success cannot
  elevate authority; sink failure is visible while retaining the primary failure.
- The repair adds no scheduler or Dagster side path. The pre-existing weekly
  compatibility refresh guarded by `transaction is None` and weekly cadence is
  outside this target run and is not a mandatory-sink route.
- Regression coverage exists in `tests/test_daily_run_sequence.py:51-61`,
  `tests/test_daily_run_early_failure.py:77-93`, and
  `packages/orchestration/tests/test_orchestration_cli_daily.py:59-68`.

## 7. Step 2 status

| status dimension | result | boundary |
|---|---|---|
| execution topology | PASS | one default generated-plan Dagster boundary; no nested execution in target run |
| real-path execution | PASS | launchd-marked wrapper reached `verity daily` and executed the compiled plan |
| fail-closed propagation | PASS | provider/preflight failure became failed step, blocked downstream, and typed `RunOutcome` |
| publication blocking | PASS | admission BLOCK, `can_publish=false`, `NOT_PUBLISHED` |
| remaining architecture debt | PRESENT, NON-DEFAULT | shadow/pilot Dagster surfaces and three explicit subprocess seams remain governed migration candidates |

Step 2 result: **PASS for the execution-spine gate, with explicitly recorded
non-default architecture debt**.

Excluded from this verdict: FRED credential availability, provider admission,
LaunchAgent drift/reconciliation, and the 14-day reliability qualification window.
