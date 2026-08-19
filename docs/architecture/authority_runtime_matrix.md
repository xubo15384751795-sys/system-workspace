# Authority and Runtime Matrix

**Status:** contract map for the active System workspace  
**Scope:** Stage A (Truth Foundation) evidence boundary  
**Last reviewed:** 2026-08-19  
**Authority:** this document describes existing authorities; it does not create a new runtime authority.

## Purpose

The System has several reports, compatibility files, dashboards, and notification
surfaces that describe the same run.  Those surfaces are useful, but they must
not become competing sources of truth.  This matrix records which implementation
owns each fact and which files are derived views.

The rule is:

> one fact → one runtime authority → many read-only projections.

The matrix is intentionally conservative.  A static check or a dry-run proves
that a contract is wired; it does **not** prove that a clean scheduled run has
produced accepted production evidence.  The latter remains the scope of SYS-15,
SYS-7, and SYS-19.

## Runtime authority matrix

| Fact | Runtime authority | Durable evidence | Derived/read-only consumers | Boundary |
|---|---|---|---|---|
| Compiled plan, step order, and dependency edges | `system_runtime.pipeline` compiled from `governance/daily_pipeline_registry.yaml` | plan payload and `plan_digest` in the run bundle | `governance/daily_run_sequence.yaml`, operator summaries, dashboards | The sequence file is a compatibility view; it must not be edited as a second scheduler definition. |
| Run execution result and exit code | `system_runtime.run_outcome.RunOutcome` | `run_outcome.json`, run events, CLI/scheduler exit status | Dagster/shell/launchd wrappers, alerts, `current_status` | Consumers serialize the same outcome; they do not recalculate exit semantics. |
| Provider attempt and fallback provenance | Harvester provider chain (`etf_market_data`, `etf_yfinance`, and provider adapters) | `provider_attempts` attached to the release/series provenance | degradation summaries, freshness/readout panels | Provider attempts explain acquisition; they never grant publish authority. |
| Observation → Measurement → Evidence → Claim → Judgment lineage | `protocols/canonical_chain.schema.json` plus `system_runtime.canonical_ids.py` | canonical chain sidecar and decision-lineage release/run bundle | publish, notification, Workbench and Learning Hub readers | Producer-side chains are diagnostic; `PublishAdmission.decision_lineage` is the authoritative Claim → Judgment input. `system_runtime.canonical_lineage` remains a bounded shadow reader. |
| Integrity and decision admission | `system_runtime.publish_admission.PublishAdmission` evaluated by `system_runtime.publish_transaction.PublishTransaction` | `admission.json`, generation lineage and digest inventory | run outcome, monitoring, notifications, status pages | `ALLOW`, `DIAGNOSTIC_ONLY`, and `BLOCK` are authoritative verdicts; missing/unknown inputs fail closed. |
| Publish transaction and current pointer | `system_runtime.publish_transaction.PublishTransaction` | transaction journal, generation manifest, `Output/current/latest_run_id.txt` | `Output/current/status.json`, system index, dashboards | Only a committed, admitted generation may change `Output/current`; failed candidates remain audit material. |
| Freshness verdict | `scripts/freshness_validator.py` | `Output/quality/freshness_report.json` and markdown projection | publish admission, status/readout, alerts | The report is a derived measurement of freshness. It cannot bypass integrity, authority, or publish checks. |
| Notifications and root-cause summary | `system_runtime.operator_events` plus the daily-run notification sink | event JSONL and alert bundle | macOS notifications, alert markdown, downstream blocked list | Notifications report the authoritative outcome; they do not alter it or create a second failure state. |
| Current status and Learning Hub views | respective builders/readers | generated status/ledger artifacts | operators and research UI | These are projections only. They cannot promote, publish, or mutate the canonical current pointer. |

## Runtime alignment matrix

Python 3.13 is the only supported active-workspace runtime.  Every execution
surface below must resolve the same locked dependency graph.

| Surface | Source of truth | Required check |
|---|---|---|
| Package declaration | `pyproject.toml` (`requires-python = ">=3.13,<3.14"`) | package metadata rejects 3.12 and 3.14 |
| Local selection | `.python-version` (`3.13`) | local tools select 3.13 before running tests or scripts |
| Dependency resolution | `uv.lock` (`requires-python = "==3.13.*"`) | `uv sync --locked --all-packages` succeeds without lock mutation |
| CI | `.github/workflows/ci.yml`, `nightly.yml`, `weekly-governance.yml` | all Python setup/matrix entries are 3.13 |
| Scheduled launcher | `scripts/resolve_system_python.sh` and launchd plists | resolver rejects any non-3.13 interpreter |
| Clean-room/install evidence | wheel/sdist plus locked sync | installed-only smoke uses the same 3.13 lock and commit |

The resolver is the runtime boundary: a local shell, launchd process, or CI
job must not silently fall back to a different Python minor version.

## Enforcement and evidence

The following checks protect the matrix or its underlying contracts:

- `scripts/check_governance_freeze.py` protects the frozen governance baseline.
- `tests/test_canonical_runtime_contracts.py` and the canonical-chain tests
  validate IDs, links, schema shape, and tamper rejection.
- `tests/test_run_outcome.py` and the daily-run consumer tests validate one
  `RunOutcome`/exit-code authority.
- `tests/test_dependency_lock.py` validates locked dependency/runtime metadata.
- `scripts/verify_control_closure.py` is a local aggregate check; it is not a
  substitute for default-path runtime evidence.

## Remaining closure work

This matrix records the intended single-authority boundary, but the following
evidence is still required before Stage A can be marked complete:

1. SYS-15: prove clean checkout, launcher, environment, commit, release, and
   plan digest are identical on the scheduled/default path.
2. SYS-7: execute a controlled manual run and two consecutive scheduled runs,
   including provider failure/recovery, degraded, blocked, and hard-failure
   cases.
3. SYS-19: reconcile run/release/generation/plan digest with canonical lineage,
   admission, publish, current, and notification evidence.

Until those checks are recorded, fixture, dry-run, dirty-checkout, and old
artifact results remain diagnostic evidence only.
