# Structural Risk Workbench

> **Governance**: See [governance/architecture_cleanup_decisions.md](governance/architecture_cleanup_decisions.md)
> for the current principles governing this project. All deferred work is in
> [governance/deferred_work_register.yaml](governance/deferred_work_register.yaml).

This is a structural-risk workbench.
It does three things:

1. collects and freezes data evidence,
2. turns evidence into risk checks and framework diagnoses,
3. exposes the current state, evidence, report, and next actions through a user-facing dashboard.

Start here:

```bash
cd /Users/a1/System
./sys check
./sys open
./sys next
```

Daily users do not need to understand the internal framework first.

For IDE and agent work, start from `MODULES.md`. Keep one workspace folder open,
then route each task through the smallest owning module in `module_contexts/`
before reading source code.

Basic use shows familiar risk evidence.
Advanced use exposes framework-specific structural diagnosis.

## System Workspace

Research operating system with three subsystems and a workspace skeleton that gives every artifact provenance and a path to canonicalisation.

## Architecture

```text
Workbench       =  Product / Tool layer          (cockpit, providers, agent harness)
Deformation     =  Framework core                (protocol input -> run package)
Learning Hub    =  Workbench governance tool      (events -> ledgers -> improvement queue)
System Index    =  cross-system index            (latest / catalog / lineage)
Sandbox         =  experimental isolation        (OpenBB / Qlib probes)
```

## Top-level Layout

```text
System/
├── Data/                                  # source of truth (durable, machine-readable)
├── Output/                                # run packages + human-facing artifacts
├── Workbench/                             # Product / Tool layer (nested git)
│   ├── src/workbench/                     # cockpit, dashboards, workspace utils
│   ├── src/nlp/                           # structural NLP library
│   ├── agents/harness/                    # agent/API harness
│   └── contracts/workbench/               # Workbench JSON schemas
├── structural-risk-harvester/             # Data Provider repo (nested git)
├── system-learning-hub/                   # Governance memory repo (nested git)
├── Structural Deformation Research System/  # Framework repo (nested git)
├── scripts/                               # workspace-level scripts (see FOLDER_OWNERSHIP.md)
├── protocols/                             # cross-module JSON schemas
├── governance/                            # constitution + authority registries
├── contracts -> Workbench/contracts
├── Structural Risk Harvester -> structural-risk-harvester/
├── Structural Research Harness -> Workbench/agents/harness/
├── System Learning Hub -> system-learning-hub/
├── ROUTING_CONSTITUTION.md
└── routing_decision_record.template.yaml
```

See `governance/repo_layout_map.md` for doc-vs-reality history and migration backlog.

Workbench owns Product/Tool source inside `Workbench/`. Harvester and Learning
Hub are **sibling repos at workspace root**, not nested under `Workbench/`.
Deformation owns Framework source. Protocols live in `protocols/` and
`Workbench/contracts/workbench/`.

## Repository Layout (multi-repo)

This workspace assembles **five** GitHub repositories. Clone the coordination repo
with submodules, or run bootstrap after a plain clone:

| Repo | Local path | Owns |
|---|---|---|
| `system-workspace` | `/` (this repo) | root docs, protocols, scripts, configs, governance |
| `Structural-Deformation-Research-System` | `Structural Deformation Research System/` | framework core (`src/core`, `src/derivation`, `src/dynamics`, …) |
| `structural-workbench` | `Workbench/` | NLP pipeline, ML signals, contracts, agent harness, tests |
| `structural-risk-harvester` | `structural-risk-harvester/` | data providers (FRED / H.4.1 / SEC / Treasury / OpenBB / …) |
| `system-learning-hub` | `system-learning-hub/` | cross-system reliability and governance memory |

Four sister repos are **git submodules** at the paths above (pinned in
`.gitmodules`). Four top-level symlinks (`Structural Research Harness`,
`System Learning Hub`, `Structural Risk Harvester`, `contracts`) provide
human-readable aliases; bootstrap recreates them on a fresh checkout.

Git policy: `governance/git_workspace_policy.md`

## Setup on a fresh device

```bash
git clone --recurse-submodules git@github.com:xubo15384751795-sys/system-workspace.git System
cd System
./scripts/bootstrap.sh         # symlinks + submodule sync + venv hints
# Or: plain clone + bootstrap (runs git submodule update --init)
# Use GH_PROTO=https ./scripts/bootstrap.sh if SSH is not available
```

The bootstrap script is idempotent — re-running pulls existing repos rather than re-cloning. After it finishes it prints venv setup commands for each sub-repo. `Data/` and `Output/` are intentionally never committed; they are regenerated by Harvester releases and Deformation runs.

## Constitution

1. **Data is the truth layer.** Output is the run/display layer. Output may reference Data; Data may not depend on Output.
2. **Promotion is explicit.** Run-local artifacts in `Output/` become canonical only by promotion into `Data/`, with a manifest entry and an updated index.
3. **Latest is a symlink.** Every script and agent must resolve through it (`find -L`, `realpath`). Treating a symlink as an empty directory is a recorded boundary violation.
4. **Sandbox is isolated.** OpenBB and Qlib probes live under `Output/sandbox/`. They cannot feed Deformation directly; promotion goes through a routing decision and a Harvester release.
5. **Every artifact has a state** in `{sandbox, run_local, candidate, canonical, archived, deprecated}`.
6. **Every gap is recorded.** Missing operator_trace, retroactive config_snapshot, latest-symlink misuse — all append to the Learning Hub runtime log under `Output/system_learning/runtime/` via `scripts/record_runtime_event.py`.

## Main Flow

```text
external providers
  -> Workbench Data Provider / Harvester acquisition / provenance
  -> Data/harvester/exports/<release_id>/                  (release artifact)
  -> Deformation src/data_access/
  -> Deformation runtime, diagnostics, UI, reports
  -> Output/deformation_runs/<run_id>/                     (run artifact)
  -> scripts/promote_snapshot.py
  -> Data/deformation/snapshots/<snapshot_id>.json         (canonical artifact)
```

System events and governance reports flow separately into `System Learning Hub`, with the machine-readable index at `Output/system_learning/latest/summary.json`.

## Workspace Scripts

```bash
python3 scripts/system_status.py        # one-screen workspace digest
python3 scripts/list_latest.py          # resolved latest paths per subsystem
python3 scripts/build_system_index.py   # regenerate Data/system_index/
python3 scripts/promote_snapshot.py --run <run_id>   # canonicalise a Deformation snapshot
./sys current                           # user-facing run cockpit
./sys evidence                          # benchmark + evidence dashboard
./sys artifacts                         # report artifact navigator
```

## Note Ownership

- Source, dataset, acquisition, and data-quality notes live in **Workbench Data Providers**.
- Structural interpretation, cases, mechanisms, variables, methods, and claims live in **Deformation**.
- Generated artifacts live in **Output**.
- Canonical (post-promotion) artifacts live in **Data**.
- Cross-system routing rules live in `ROUTING_CONSTITUTION.md` and the Agent Routing module.

## Deformation Downscope

Deformation should not continue growing as a data acquisition system.

Keep in Deformation:

- `src/core`, `src/derivation`, `src/dynamics`, `src/operators`
- `src/proxies`, `src/diagnostics`, `src/validation`
- framework-specific benchmark evaluation
- case replay and scenario labs
- framework-specific runtime and interpretation surfaces
- wiki, paper, and claim governance
- thin `src/data/gateway/` shim over `src/data_access/`

Move or freeze out of Deformation:

- provider-specific downloaders
- raw/processed data ownership
- corpus acquisition providers
- dataset source documentation
- acquisition or source-validation notebooks
- data-agent prompts
- source registry publication
- Harvester bundle creation
- generated benchmark report artifacts
- generic UI/API/report rendering and artifact navigation
- generic benchmark evidence dashboards

## Sparse Activation Routing

Default posture: smallest sufficient expert set first. Add experts when a task crosses layer boundaries, touches protected artifacts, triggers coupling rules, or prepares an output for release.

- `ROUTING_CONSTITUTION.md`: global deny rules, layer authority, activation discipline.
- `routing_decision_record.template.yaml`: auditable record template for non-trivial routing decisions; concrete records live under `Output/system_learning/routing_decisions/`.

## Outstanding Workspace Gaps

Recorded in `Output/system_learning/events/events_2026-05-03.jsonl` and surfaced by `scripts/system_status.py`:

| Gap                                                              | Owner                                  | Action                                                    |
|------------------------------------------------------------------|----------------------------------------|-----------------------------------------------------------|
| `operator_trace.jsonl` missing in `2026-04-22_WEEKLY`            | Structural Deformation Research System | Runner must emit one JSON object per applied operator.    |
| `config_snapshot.json` was backfilled, not captured at run time  | Structural Deformation Research System | Runner must serialise resolved config before completing.  |
| `latest` symlink misuse risk                                     | Workspace / agents                     | Always inspect via `find -L` / `realpath`.                |
