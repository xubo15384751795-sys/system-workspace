# Submodule Pin Cleanup Plan

**Status:** open task carried over from `governance/repo_state_audit.md` §3 step 3
**Snapshot taken:** 2026-05-22

After Phase 1 locked the submodule layout, all four sister repos still carry
**uncommitted in-flight work**. The parent gitlink cannot be updated until each
sister repo commits (or stashes) its own changes. This document inventories the
dirty surface and recommends commit slicing so the parent pin is updated in one
clean pass.

> Decision (2026-05-22): write the plan, leave actual commits to the user. The
> commit message wording, granularity, and what counts as work-in-progress are
> not auditor decisions.

---

## 1. `Workbench/` — largest dirty surface

**Primary theme:** agent harness rename `agent_harness/structural-research-harness/` → `agents/harness/` (matches Phase 1 doc decision).

**Secondary themes mixed in:**
- governance modules added (`src/workbench/governance/incident.py`, `*.py` modifications)
- ML signal additions (`gluonts_regime_forecaster.py`, `governance_signal.py`)
- C005 morphology product entries (`c005_morphology_replay.py`, `c005_morphology_report.py`)
- event consumer (`agents/harness/events/event_consumer.py`, `tests/test_event_consumer.py`)
- workspace path / contract refactors

### Recommended commit slicing

| # | Theme | Files |
|---|---|---|
| 1 | Rename harness path | all `D agent_harness/…` + `A agents/harness/…` (use `git mv` retroactively if possible: `git add -A && git commit -m "rename agent_harness/structural-research-harness → agents/harness"`) |
| 2 | Update tests / paths for new harness | `tests/conftest.py`, `tests/test_freshness.py`, `src/workbench/paths.py`, `src/workbench/workspace/_paths.py` |
| 3 | Governance product additions | `src/workbench/governance/*.py`, `src/workbench/contract_validator.py`, `src/workbench/framework_registry.py`, `src/workbench/freshness.py`, `src/workbench/workspace/build_system_index.py`, `src/workbench/workspace/promote_snapshot.py` |
| 4 | ML / GluonTS layer | `src/ml/ml_signal_writer.py`, `src/ml/gluonts_regime_forecaster.py`, `src/ml/governance_signal.py`, `src/benchmarks/market_feedback/sandbox_exporter.py`, `tests/test_gluonts_regime_forecaster.py`, `tests/test_ml_governance_signal.py` |
| 5 | C005 morphology surface | `src/workbench/c005_morphology_*.py`, `src/workbench/demo.py` |
| 6 | Event consumer (new contract) | `agents/harness/events/event_consumer.py`, `tests/test_event_consumer.py`, `tests/test_e2e_integration.py` |
| 7 | Housekeeping | `.gitignore`, `README.md`, `pyproject.toml` |

> Slices 1+2 are the only ones strictly required to unblock parent pin update.
> Slices 3–7 can be deferred to a follow-up branch if any are still
> work-in-progress.

---

## 2. `structural-risk-harvester/`

**Primary theme:** provider hardening + ops/quality additions.

| Bucket | Files |
|---|---|
| Provider patches | `src/harvester/providers/h41.py`, `src/harvester/providers/openbb_provider.py`, `src/harvester/providers/README.md`, `configs/series_registry.yaml` |
| Audit / quality | `src/harvester/audit/index.py`, `src/harvester/quality/__init__.py`, `src/harvester/quality/report.py` (new), `src/harvester/ops.py` (new), `tests/test_audit_index.py`, `tests/test_quality_report.py` (new), `tests/test_ops.py` (new), `tests/conftest.py` (new) |
| Exporter | `src/harvester/core/exporter.py`, `tests/test_export_immutability.py` |
| CLI / official surface | `src/harvester/cli.py`, `src/harvester/official.py` |
| Boundary tests | `tests/test_openbb_boundary.py`, `tests/test_providers_h41.py` |
| Docs / new dir | `README.md` (new), `docs/operations.md` (new), `scripts/` (new untracked dir) |

> `scripts/` untracked dir is a candidate landing zone for `openbb_secondary_audit.py`
> / `repair_openbb_entrypoints.py` from the parent `scripts/` migration — coordinate.

---

## 3. `system-learning-hub/`

**Primary theme:** runtime layer + cartography + governance memory build-out.
**This is the Hub absorbing the runtime log contract.**

| Bucket | Files |
|---|---|
| Runtime layer (new) | `src/system_learning/runtime/{__init__,context,manifest,paths,pipeline,record}.py`, `tests/test_runtime.py`, `tests/test_runtime_record.py` |
| Cartography (new) | `src/system_learning/cartography/{__main__,runner}.py`, `src/system_learning/cartography/report.py`, `scripts/codebase_cartographer.py` |
| Analyzers | `src/system_learning/analyzers/{derive,edges,governance_pressure,recurrence}.py` |
| Governance memory | `src/system_learning/governance/{__init__,lifecycle,lifecycle_events,verify}.py`, `tests/test_governance_memory.py` |
| Ledger | `src/system_learning/ledger/{append,query,store}.py` |
| ML integrity | `src/system_learning/ml_integrity/{__main__,runner}.py` |
| Reports | `src/system_learning/reports/{__init__,writer}.py` |
| Schema | `src/system_learning/schema.py`, `src/system_learning/schema/events.py` |
| Ingestion / CLI | `src/system_learning/ingestion/collectors.py`, `src/system_learning/cli.py` |
| Housekeeping | `.gitignore`, `README.md`, `pyproject.toml`, `data` (untracked — should be `data → symlink`, verify before commit) |
| Test plumbing | `tests/test_hub.py` |

> `MM` (modified in both index + working tree) on `cli.py`, `README.md`,
> `ingestion/collectors.py` etc. means a staged version exists and was modified
> again. Resolve before committing.

> **Critical:** `data` is the symlink to `Data/system_learning/`. It is untracked
> currently, which is correct (symlink lives at bootstrap level). Confirm
> `.gitignore` excludes it before staging.

---

## 4. `Structural Deformation Research System/`

**Primary theme:** DataHub bridge + proxy series map + GluonTS anomaly detector.

| Bucket | Files |
|---|---|
| Data layer | `src/data/data_sources.py`, `src/data/gateway/{bridge,data_hub,data_hub_lite}.py`, `src/data/proxy_series_map.py` (new), `tests/test_data_hub_bridge.py` (new), `tests/test_data_hub_lite.py`, `tests/test_data_source_selection.py` |
| ML integration | `src/ml/gluonts_anomaly_detector.py` (new) |
| Output / runtime | `src/output/run_package.py`, `src/runtime/assembly.py`, `tests/test_output_exporter.py` |
| Scripts | `scripts/dual_path_compare.py`, `scripts/run_premise_audit.py` (new) |
| Housekeeping | `README.md`, `config.yaml`, `framework.yaml` (new) |

---

## 5. After each sister repo commits

From the workspace root:

```bash
cd /Users/a1/System

# After each submodule commits, update parent gitlink:
git add Workbench
git add structural-risk-harvester
git add system-learning-hub
git add "Structural Deformation Research System"

git status   # confirm only submodule pin entries are staged
git commit -m "Update submodule pins after sister-repo work-in-flight commits"
```

`git status --short` on the parent should then show **clean submodule lines
without the lowercase `m` prefix**.

---

## 6. Caveats

- **Do not run `git submodule update --remote`** before the sister repos commit —
  it will discard the in-flight work.
- **`scripts/` migration debt** (parent repo): the deprecation banners added
  2026-05-22 mean the parent `scripts/` files can stay where they are. Physical
  migration into `<submodule>/scripts/` should happen **after** this plan
  executes, on a fresh branch, paired with thin wrapper shims at the old paths.
- **`Workbench/agents/harness/events/system_event_writer.py`** is listed in
  `governance/runtime_log_contract.md` as a deprecated peer writer. When
  slicing Workbench commit #6, consider whether this file should be deleted
  rather than re-added under the new path. Coordinate with the runtime log
  migration.
