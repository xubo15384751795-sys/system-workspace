# Repository Layout Map

**Status:** current reality as of 2026-05-22  
**Policy:** docs follow on-disk reality (locked 2026-05-22). Sister repos stay as **top-level submodules**; physical nest under `Workbench/` is **retired**.

This file is the authoritative map when `FOLDER_OWNERSHIP.md`, older README
sections, or bootstrap history disagree with the tree on disk.

---

## 1. Sister repositories (git submodules)

| Repo | Actual path | Submodule |
|---|---|---|
| `system-workspace` | `/` (this repo) | — |
| `structural-workbench` | `Workbench/` | yes |
| `Structural-Deformation-Research-System` | `deformation-framework/` | yes |
| `structural-risk-harvester` | `structural-risk-harvester/` | yes |
| `system-learning-hub` | `system-learning-hub/` | yes |

Registered in `.gitmodules`. Parent pins each sister repo at a commit; see
`governance/git_workspace_policy.md` for clone/update workflows.

### Sibling knowledge repo (not a submodule)

| Repo | Actual path | Role |
|---|---|---|
| Paper (`case-lab`) | `$PAPER_ROOT` (default `/Users/a1/Paper`) | World model source — cases, mechanisms, variables, indicators |
| | | Synced into `Data/paper_world_model/` via `scripts/sync_paper_world_model.py` |
| | | Feedback drafts exported to `Paper/40_Review/_inbox/` via `scripts/export_feedback_to_paper.py` |

Paper is edited in Obsidian and connected by file-system pipes, not git submodule pins.
Set `PAPER_ROOT` when the vault lives outside the default path.

### Retired doc paths (do not use)

| Old canonical path in docs | Why wrong |
|---|---|
| `Workbench/data_providers/structural-risk-harvester/` | directory never created; harvester lives at repo root |
| `Workbench/governance/system-learning-hub/` | directory never created; hub lives at repo root |
| `Workbench/agent_harness/structural-research-harness/` | harness lives at `Workbench/agents/harness/` |

---

## 2. Compatibility symlinks (human-readable aliases)

| Symlink | Target | Purpose |
|---|---|---|
| `Structural Risk Harvester` | `structural-risk-harvester/` | legacy name / IDE navigation |
| `System Learning Hub` | `system-learning-hub/` | legacy name; hub runtime resolves this first |
| `Structural Research Harness` | `Workbench/agents/harness/` | legacy name for agent harness |
| `contracts` | `Workbench/contracts/` | Workbench contract root |

Symlinks are optional for tooling that uses kebab-case paths directly, but
should exist on a fresh bootstrap checkout.

---

## 3. Module → path routing

| Module | Source (edit here) | Generated / consumed artifacts |
|---|---|---|
| Workbench product | `Workbench/src/workbench/` | `Output/current/`, `Output/workbench/` |
| Structural NLP | `Workbench/src/nlp/` | `Data/nlp/`, protocol-shaped exports |
| Agent harness | `Workbench/agents/harness/` | hooks, tools, routing helpers |
| Harvester | `structural-risk-harvester/` | `Data/harvester/exports/` |
| Learning Hub | `system-learning-hub/` | see §4 |
| Deformation Framework | `deformation-framework/` | `Output/deformation_runs/`, promoted `Data/deformation/` |
| Workspace protocols | `protocols/` + `Workbench/contracts/workbench/` | JSON schemas |
| Workspace constitution | `governance/` | authority registries, proxy spec |

---

## 4. `system_learning` truth matrix

| Path | Role | Truth? | Writer |
|---|---|---|---|
| `Output/system_learning/runtime/` | append-only runtime log | **yes — canonical chronology** | Learning Hub only |
| `Data/system_learning/` | ledgers, registries | **yes — canonical data** | Learning Hub only |
| `Output/system_learning/latest/` | derived reports | **yes — canonical runtime output** | Learning Hub only |
| `Output/system_learning/events/` | legacy peer sensor output | **deprecated** | none (migration) |
| `Workbench/Output/system_learning/` | removed | **n/a** | n/a |
| `system-learning-hub/data/` | symlink → `Data/system_learning/` | **alias only** | bootstrap |

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
| `Workbench/src/workbench/governance/` | product-side governance UI/helpers (if present) |
| `system-learning-hub/` | governance **memory tool** — orchestrates learning events, does not replace `governance/` |

---

## 6. Top-level `scripts/` inventory

### Thin wrappers (delegate to `Workbench/src/workbench/`)

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

### Module-owned scripts (in-place marked 2026-05-22, physical move pending)

Each script below carries a `DEPRECATED LOCATION (marked 2026-05-22)` banner in
its header pointing to the target submodule. **Files are not yet moved**; they
remain at `scripts/` so `sys`, Justfile, tests, and config references keep
working. Physical migration happens after the submodule pin cleanup
(`governance/submodule_commit_plan.md`), paired with thin wrappers.

| Script | Should live in | Banner present? |
|---|---|---|
| `structural_replay_v2.py`, `structural_replay_evaluation.py`, `run_c005_morphology_replay.py`, `build_c005_morphology_report.py` | `deformation-framework/scripts/` | ✓ |
| `nlp_ingest.py`, `nlp_extract.py`, `ask_evidence.py` | `Workbench/` CLI entry | ✓ |
| `openbb_secondary_audit.py`, `repair_openbb_entrypoints.py` | `structural-risk-harvester/scripts/` | ✓ |
| `framework_cli.py` | `Workbench/` or Framework CLI (TBD) | ✓ |
| `audit_boundaries.py`, `prepare_dl_training_data.py` | workspace audit / research utilities | ✓ |

### Internal / maintenance

```text
_paths.py, _audit_coupling.py, _count_project.py, _check_data.py
_run_descriptive_quality_tests.py, github_preflight.py, bootstrap.sh
```

---

## 7. Planned migrations (remaining)

1. ~~Register four sister repos as git submodules~~ (done 2026-05-22)
2. ~~Consolidate duplicate `system_learning` trees~~ (done 2026-05-22)
3. ~~Mark non-wrapper scripts with deprecation banner pointing to target submodule~~ (done 2026-05-22, evening)
4. ~~Archive legacy `Output/system_learning/events/*.jsonl`~~ (done 2026-05-22, evening)
5. **Submodule pin cleanup**: each sister repo commits in-flight work; parent updates gitlinks. Plan: `governance/submodule_commit_plan.md`.
6. **Physical migration** of the 12 marked scripts into their target submodule `scripts/` directories — only after step 5 lands, with thin wrappers retained at parent `scripts/`.
7. **Peer-writer retirement**: route remaining `Output/system_learning/events/` writers through `system_learning record` (cross-submodule cleanup).

Retired: nest harvester/hub under `Workbench/` — do not pursue without a new migration plan.

See `governance/repo_state_audit.md` for phase plan and risks, and
`governance/submodule_commit_plan.md` for step 5 details.
