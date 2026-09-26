# Step 5 — Structural Cleanup Status

Status: **COMPLETE_WITH_PRODUCTION_RESTORE_DEFERRED**

The first bounded slice is complete: the root distribution now exposes
`verity = verity.cli:main`. The implementation is in
`verity/cli/_application.py`; `system_cli.app:main` remains a compatibility
alias for one explicit release cycle. The focused CLI, execution-spine, and
pipeline-contract tests pass.

The daily God module has completed the bounded responsibility extraction:
compiled step dispatch now lives in `verity/cli/run_coordinator.py`, and
schedule/compatibility admission helpers live in
`verity/cli/schedule_admission.py`. Post-run trace capture, feedback-pending
generation, runtime-event emission, and alert emission now live in
`verity/cli/post_run_sinks.py`. Candidate lineage, requested-authority
mapping, transaction-failure mapping, and live-index refresh helpers now live
in `verity/cli/publication_coordinator.py`; the application still owns the
final publication decision. The daily-run closure records behavior parity as
PASS.

The current structural scan also confirms three zero-count boundaries:

- production package → `scripts` imports: 0;
- production `sys.path` mutation: 0;
- production operator-specific absolute paths: 0.

The registry authoring split is now closed.  The six concern-specific sources
under `governance/pipeline/` are merged by one typed loader into one
`CompiledPipeline`; the historical `daily_pipeline_registry.yaml` is marked
`DERIVED` and remains only as a parity/compatibility view.  The before/after
compiled-plan digest and step/DAG/entrypoint/profile/timeout/failure/freshness/
monitoring/ownership/schedule parity audit pass in
`tools/audit/registry_authoring_convergence.py`.

The build/generated layout contract is also closed as a non-destructive slice:
`governance/layout_contract.yaml` defines source checkout, source archive,
installed runtime, and build/dist behavior.  The current 32 non-cache
symlinks are classified as `COMPATIBILITY`, `GENERATED`, or `MIGRATE`; no
link was removed or dereferenced.  The automated layout audit passes, while
the eight migration-class links remain explicitly deferred for a later,
separately approved cleanup batch.

The default compiled plan still invokes one explicitly justified archived
executable from `packages/framework_v1_archive`; its legacy callable field is
metadata only and is not the runtime invocation. Two additional archive
compatibility callables remain registered for `on_demand` use. Step 5E is now
split into two independent restore gates. The structural restore-fidelity
target is the accepted r10 generation
`daily_pipeline_20260912_142103_a67e12`. Its isolated temporary restore copied
45 generation files and passed generation completeness, manifest validity,
artifact availability, explicit restore point, reader graph, artifact
inventory, content digest, manifest, lineage/index/registry, and
pointer/publication parity checks. The restored state remained
`DIAGNOSTIC_ONLY`, retained claim ceiling `structural_diagnostic`, and kept
`allows_decision_consumers=false`. No production pointer or authority was
changed. Therefore **5E-A Structural Restore Fidelity = PASS**.

The same preflight scans 21 generation manifests and finds zero production
authority restore targets. `production_baseline_v1` remains
`DIAGNOSTIC_ONLY`, and the remaining accepted generations are either
`DIAGNOSTIC_ONLY` or `BLOCK`. Therefore **5E-B Production-Authority Restore =
BLOCKED_NO_ELIGIBLE_PRODUCTION_TARGET** and is carried forward to Step 6
production recovery / target-environment proof. The existing production
eligibility rule was not lowered, and no diagnostic generation was treated as
production or made available to decision consumers. A subsequent real scheduled-path rehearsal
(`daily_pipeline_20260912_142103_a67e12`) consumed the finalized
`2026-09-12-r10` release and committed successfully through the same
generated-plan spine. Runtime evidence records one `daily_compiled_plan_job`
Dagster run (`406804d8-9ae6-4549-b522-f81d500baaf7`) with 32/32 steps
successful and no blocked steps. It recorded a successful FRED attempt, but
its aggregate provider status remained `partial_provider_success`; admission
reported `PROVIDER_DECISION_CONDITIONAL` and `FRESHNESS_WARN`, with
`availability.decision_usable=false`. Its authority is therefore still
`DIAGNOSTIC_ONLY`. The r10 release gate now reports required series present
and model-input freshness as PASS; the prior false provider-native/canonical
model-input warning is absent. Production restore-point selection remains
blocked before any production restore or pointer rewrite. The only
restore-like operation was the bounded, isolated temporary structural fidelity
drill described above.

The independent closure regression slices remain green: 98 root-side
architecture/execution/publication/restore-contract tests and 21 Harvester
parity/concurrency tests passed in separate pytest processes. The bounded
Harvester promotion-gate fix also passed 70 focused tests covering Phase C,
registry outcome, and Treasury acquisition behavior. The existing DVC data
restore manifest verifies as `PASS`; it is recorded separately and is not
substituted for the generation restore proof. The Step 5E structural fidelity
test and Step 5F closure audit now pass with the production-authority restore
explicitly deferred.
The final closure rerun also passed 38 focused root-side tests, 83 focused
Harvester tests, and the restore-preflight test; `git diff --check` passed.

Data/Output cleanup is deliberately deferred. No reset, clean, stash, delete,
production restore, or production pointer rewrite was performed. Provider
admission, reliability qualification, and LaunchAgent reconciliation remain
outside this structural gate. The machine-readable closure reports the
production-authority restore as `DEFERRED_STEP6`; it does not imply a
production-authority PASS.

The machine-readable status and repeatable read-only audit are:

- `governance/step5_structural_cleanup.yaml`
- `tools/audit/step5_structural_cleanup.py`
- `tools/audit/restore_generation_preflight.py`
