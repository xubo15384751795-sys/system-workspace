# Folder Ownership

Directory-level boundary map for `/Users/a1/System`. This file describes **what
is on disk now**, not a future nested layout under `packages/workbench/`.

Last aligned: 2026-05-22. See `governance/repo_layout_map.md` for the full
doc-vs-reality table and migration backlog.

---

## Workspace skeleton

```text
System/                                    # system-workspace (this git repo)
├── Data/                                  # canonical durable artifacts
├── Output/                                # run packages + human-facing views
├── protocols/                             # cross-module JSON schemas
├── governance/                            # constitution + authority registries
├── scripts/                               # workspace entrypoints (see below)
├── tests/                                 # workspace-level tests
├── packages/workbench/                             # structural-workbench (git submodule)
├── packages/harvester/             # harvester repo (git submodule)
├── packages/learning_hub/                   # learning hub repo (git submodule)
├── packages/framework/  # framework repo (git submodule)
├── contracts -> packages/workbench/contracts       # compatibility symlink
├── Structural Risk Harvester -> packages/harvester/
├── System Learning Hub -> packages/learning_hub/
└── Structural Research Harness -> packages/workbench/agents/harness/
```

Four sister repositories are **sibling directories** and **git submodules**,
not nested under `packages/workbench/data_providers/` or `packages/workbench/governance/`.
See `governance/git_workspace_policy.md`.

---

## Tool / Product Layer

### Workbench (product + NLP + contracts)

```text
packages/workbench/                                 # git submodule: structural-workbench
├── src/workbench/                         # product cockpit, dashboards, workspace utils
├── src/nlp/                               # structural NLP library
├── src/ml/                                # ML signal layer
├── contracts/workbench/                   # Workbench JSON schemas + templates
├── agents/harness/                        # agent/API harness (tools, hooks, routing)
├── tests/
├── Data/                                  # Workbench-local data (gitignored)
└── Output/                                # Workbench-local output (not workspace truth)
```

User-facing generated artifacts for the whole workspace:

```text
Output/current/
Output/workbench/
```

Top-level `./sys` and the thin wrappers listed below delegate into
`packages/workbench/src/workbench/`.

### Harvester (data provider)

```text
packages/harvester/               # git submodule — canonical source
Data/harvester/exports/                  # published release bundles
```

`Structural Risk Harvester/` is a compatibility symlink to the directory above.

### Learning Hub (governance memory tool)

```text
packages/learning_hub/                     # git submodule — canonical source
Data/system_learning/                    # canonical ledgers + registries (Hub writes)
Output/system_learning/runtime/          # append-only runtime log (Hub writes)
Output/system_learning/latest/           # derived reports (Hub writes)
```

Peer modules record via `scripts/record_runtime_event.py` only. See
`governance/runtime_log_contract.md`.

---

## Structural NLP Library

```text
packages/workbench/src/nlp/
```

Owns ingestion, extraction, mapping, candidate export, promotion, and
NLP-domain protocol shapes. Root `protocols/nlp_*.schema.json` files are
compatibility mirrors during library-side consolidation.

Wrappers (must stay thin):

```text
scripts/nlp_ingest.py
scripts/nlp_extract.py
```

---

## Protocol Layer

Cross-module schemas:

```text
protocols/                               # workspace handoff schemas
packages/workbench/contracts/workbench/           # Workbench contract catalog
```

`contracts/` at repo root symlinks to `packages/workbench/contracts/`.

---

## Framework Core

```text
packages/framework/  # git submodule — canonical source
```

Framework-owned areas include `src/proxies/`, `src/derivation/`, `src/operators/`,
`src/diagnostics/`, `src/dynamics/`, `src/interpretation/`, `src/core/`,
`src/claims/`, `wiki/`, `papers/`.

Framework code produces protocol-shaped outputs. It does not own Workbench
product workflows or generic workspace scripts.

---

## Agent / API Harness

```text
packages/workbench/agents/harness/
```

Agent-facing tools, hooks, policies, skills, and workflow guards. Tool /
Workbench code — not Framework code.

`Structural Research Harness/` symlinks here.

---

## Workspace scripts (`scripts/`)

### Thin wrappers only (canonical logic in `packages/workbench/src/workbench/`)

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

### Still at workspace root (owner migration pending)

Framework replay, morphology, OpenBB audit, NLP extract, boundary audit, and
similar scripts live here for historical entrypoints. They belong to their
owning module repos per `governance/repo_layout_map.md` §6. Do not add new
non-wrapper logic at this layer.

Workspace utilities:

```text
bootstrap.sh
framework_cli.py
audit_boundaries.py
```

---

## Constitution-Level Red Line

Tool, Framework, and Data Provider layers must not directly understand each
other. They communicate only through protocols and published artifacts.

Direct imports, hidden path coupling, semantic field peeking outside a contract,
or code that turns one layer into another layer's internal adapter are severe
boundary violations.
