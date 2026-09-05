# Repository Layout Map

**Status:** migration record plus current package snapshot as of 2026-08-12
**Policy:** the active source tree is the root monorepo under `packages/`.
The submodule and pre-consolidation paths retained below are historical records,
not current clone or update instructions.

This file is the authoritative map when `FOLDER_OWNERSHIP.md`, older README
sections, or bootstrap history disagree with the tree on disk.

---

## 0. Current canonical workspace

| Package | Active path | Role |
|---|---|---|
| `system-workspace` | `/` | root docs, protocols, scripts, configs, governance |
| `structural-workbench` | `packages/workbench/` | product, NLP, contracts, agent harness |
| `Structural-Deformation-Research-System` | `packages/framework_v1_archive/` | Deformation v1 evidence archive |
| `structural-risk-harvester` | `packages/harvester/` | data providers and release production |
| `system-learning-hub` | `packages/learning_hub/` | reliability and governance memory |
| `system-orchestration` | `packages/orchestration/` | Dagster/runtime orchestration |

This checkout has no `.gitmodules`, no Git-linked package entries, and no
nested package repositories. `scripts/bootstrap.sh` verifies the package layout
and recreates compatibility symlinks only.

## 1. Historical pre-consolidation layout (git submodules)

| Repo | Actual path | Submodule |
|---|---|---|
| `system-workspace` | `/` (this repo) | — |
| `structural-workbench` | `Workbench/` | yes |
| `Structural-Deformation-Research-System` | `deformation-framework/` | yes |
| `structural-risk-harvester` | `structural-risk-harvester/` | yes |
| `system-learning-hub` | `system-learning-hub/` | yes |

This was the pre-consolidation layout. Its paths, pins, and `.gitmodules`
references are retained for migration provenance only; do not use them for a
fresh checkout.

### Sibling knowledge repo (not a submodule)

| Repo | Actual path | Role |
|---|---|---|
| Paper (`case-lab`) | `$PAPER_ROOT` (default `/Users/a1/Paper`) | World model source — cases, mechanisms, variables, indicators |
| | | Synced into `Data/paper_world_model/` via `scripts/sync_paper_world_model.py` |
| | | Feedback drafts exported to `Paper/40_Review/_inbox/` via `scripts/commands/weekly/export_feedback_to_paper.py` |

Paper is edited in Obsidian and connected by file-system pipes, not git submodule pins.
Set `PAPER_ROOT` when the vault lives outside the default path.

### Retired doc paths (do not use)

| Old canonical path in docs | Why wrong |
|---|---|
| `Workbench/data_providers/structural-risk-harvester/` | directory never created; active source is `packages/harvester/` |
| `Workbench/governance/system-learning-hub/` | directory never created; active source is `packages/learning_hub/` |
| `Workbench/agent_harness/structural-research-harness/` | directory never created; active harness is `packages/workbench/agents/harness/` |

---

## 2. Compatibility symlinks (active aliases)

| Symlink | Target | Purpose |
|---|---|---|
| `Structural Risk Harvester` | `packages/harvester/` | legacy name / IDE navigation |
| `System Learning Hub` | `packages/learning_hub/` | legacy name; hub runtime resolves this first |
| `Structural Research Harness` | `packages/workbench/agents/harness/` | legacy name for agent harness |
| `contracts` | `packages/workbench/contracts/` | Workbench contract root |

Symlinks are optional for tooling that uses kebab-case paths directly, but
should exist on a fresh bootstrap checkout.

---

## 3. Module → path routing

| Module | Source (edit here) | Generated / consumed artifacts |
|---|---|---|
| Workbench product | `packages/workbench/src/workbench/` | `Output/current/`, `Output/workbench/` |
| Structural NLP | `packages/workbench/src/nlp/` | `Data/nlp/`, protocol-shaped exports |
| Agent harness | `packages/workbench/agents/harness/` | hooks, tools, routing helpers |
| Harvester | `packages/harvester/` | `Data/harvester/exports/` |
| Learning Hub | `packages/learning_hub/` | see §4 |
| Deformation v1 evidence archive | `packages/framework_v1_archive/` | `Output/deformation_runs/`, promoted `Data/deformation/` |
| Orchestration | `packages/orchestration/` | Dagster jobs and runtime entrypoints |
| Workspace protocols | `protocols/` + `packages/workbench/contracts/workbench/` | JSON schemas |
| Workspace constitution | `governance/` | authority registries, proxy spec |

---

## 4. `system_learning` truth matrix

| Path | Role | Truth? | Writer |
|---|---|---|---|
| `Output/system_learning/runtime/` | append-only runtime log | **yes — canonical chronology** | Learning Hub only |
| `Data/system_learning/` | ledgers, registries | **yes — canonical data** | Learning Hub only |
| `Output/system_learning/latest/` | derived reports | **yes — canonical runtime output** | Learning Hub only |
| `Output/system_learning/events/` | legacy peer sensor output | **deprecated** | none (migration) |
| `packages/workbench/Output/system_learning/` | removed | **n/a** | n/a |
| `packages/learning_hub/data/` | symlink → `Data/system_learning/` | **alias only** | bootstrap |

Peer modules **read** Hub outputs; they **record** only via `scripts/record_runtime_event.py`
or `python3 -m system_learning record`. See `governance/runtime_log_contract.md`.

---

## 5. `governance` directory matrix

| Path | Role |
|---|---|
| `governance/` | workspace constitution: proxy spec, module authority, semantic registry |
| `Output/governance/` | generated governance run artifacts |
| `docs/governance/` | human-readable governance docs |
| `tests/governance/` | anti-gaming and gate tests |
| `packages/workbench/src/workbench/governance/` | product-side governance UI/helpers (if present) |
| `packages/learning_hub/` | governance **memory tool** — orchestrates learning events, does not replace `governance/` |

---

## 6. Top-level `scripts/` compatibility inventory

### Thin wrappers (delegate to `packages/workbench/src/workbench/`)

```text
refresh_output_current.py
build_benchmark_evidence_dashboard.py
build_artifact_navigator.py
validate_workbench_contract.py
build_system_index.py
list_latest.py
promote_snapshot.py
system_status.py
```

### Module-owned scripts and entrypoints

Package-owned code is under `packages/framework_v1_archive/` (evidence archive),
`packages/harvester/`, `packages/learning_hub/`, and `packages/workbench/`.
Root compatibility scripts remain where the runtime and `sys` surface require
them. The current script ownership and lifecycle inventory is
`governance/entrypoint_registry.yaml`, checked by
`tests/test_entrypoint_registry_completeness.py`; this avoids maintaining a
second hand-written list of historical filenames here.

### Internal / maintenance

```text
_paths.py, _audit_coupling.py, _count_project.py, _check_data.py
_run_descriptive_quality_tests.py, github_preflight.py, bootstrap.sh
```

---

## 7. Historical migration record

1. ~~Register four sister repos as git submodules~~ (historical, 2026-05-22)
2. ~~Consolidate duplicate `system_learning` trees~~ (historical, 2026-05-22)
3. ~~Mark non-wrapper scripts with deprecation banners~~ (historical, 2026-05-22)
4. ~~Archive legacy `Output/system_learning/events/*.jsonl`~~ (historical, 2026-05-22)
5. **Submodule pin cleanup and physical migration** are superseded by the
   active `packages/` monorepo; `governance/submodule_commit_plan.md` remains
   migration provenance and is not an execution plan.
6. **Peer-writer retirement** is tracked by the current Learning Hub contracts,
   not by cross-submodule updates.

Historical retired option: nest harvester/hub under `Workbench/` — do not pursue
without a new migration plan.

See `governance/repo_state_audit.md` for phase plan and risks, and
`governance/submodule_commit_plan.md` for step 5 details.

---

## 8. Harvester data path canonicalization (Phase 4.1, 2026-07-18)

The harvester exports root has two historical paths:
- **Canonical:** `Data/harvester/exports/` (the live `latest` symlink target;
  what `system_runtime.paths.WorkspacePaths.harvester_exports` returns).
- **Legacy alias:** `packages/harvester/data/` (from when the harvester was a
  standalone package with its own data dir).

`harvester.core.exporter.default_exports_root()` now resolves to the canonical
path via `WorkspacePaths`, falling back to the legacy `parents[3]/data/exports`
only when `system_runtime` is not importable (standalone-testability). New code
MUST use `WorkspacePaths.harvester_exports` or `default_exports_root()`, never
a raw `Path(__file__).parents[3] / "data"`. The `packages/harvester/data`
directory is a symlink alias and must not be written to directly.
