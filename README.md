# Structural Risk Workbench

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
├── Workbench/                             # Product / Tool layer source
│   ├── data_providers/structural-risk-harvester/
│   └── agent_harness/structural-research-harness/
│   └── governance/system-learning-hub/
├── scripts/                               # workspace-level scripts (see below)
├── contracts -> Workbench/contracts
├── Structural Risk Harvester -> Workbench/data_providers/structural-risk-harvester
├── Structural Research Harness -> Workbench/agent_harness/structural-research-harness
├── Structural Deformation Research System/# Deformation source code
├── System Learning Hub -> Workbench/governance/system-learning-hub
├── ROUTING_CONSTITUTION.md                # always-active routing rules
├── expert_activation_map.yaml             # task-to-expert routing map
└── routing_decision_record.template.yaml  # template for non-trivial routing decisions
```

Workbench owns Product/Tool source, including data providers, agent harnesses, governance memory, workspace utilities, and protocol contracts. Deformation owns Framework source. Protocols are available through `contracts/workbench/` as a compatibility path.

## Constitution

1. **Data is the truth layer.** Output is the run/display layer. Output may reference Data; Data may not depend on Output.
2. **Promotion is explicit.** Run-local artifacts in `Output/` become canonical only by promotion into `Data/`, with a manifest entry and an updated index.
3. **Latest is a symlink.** Every script and agent must resolve through it (`find -L`, `realpath`). Treating a symlink as an empty directory is a recorded boundary violation.
4. **Sandbox is isolated.** OpenBB and Qlib probes live under `Output/sandbox/`. They cannot feed Deformation directly; promotion goes through a routing decision and a Harvester release.
5. **Every artifact has a state** in `{sandbox, run_local, candidate, canonical, archived, deprecated}`.
6. **Every gap is recorded.** Missing operator_trace, retroactive config_snapshot, latest-symlink misuse — all surface as Learning Hub events under `Output/system_learning/events/`.

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
- Cross-system routing rules live in `ROUTING_CONSTITUTION.md` and `expert_activation_map.yaml`.

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
- `expert_activation_map.yaml`: task-to-expert routing map for prompt protocols, claim guardians, UI / Harvester boundaries, and Learning Hub governance.
- `routing_decision_record.template.yaml`: auditable record template for non-trivial routing decisions; concrete records live under `Output/system_learning/routing_decisions/`.

## Outstanding Workspace Gaps

Recorded in `Output/system_learning/events/events_2026-05-03.jsonl` and surfaced by `scripts/system_status.py`:

| Gap                                                              | Owner                                  | Action                                                    |
|------------------------------------------------------------------|----------------------------------------|-----------------------------------------------------------|
| `operator_trace.jsonl` missing in `2026-04-22_WEEKLY`            | Structural Deformation Research System | Runner must emit one JSON object per applied operator.    |
| `config_snapshot.json` was backfilled, not captured at run time  | Structural Deformation Research System | Runner must serialise resolved config before completing.  |
| `latest` symlink misuse risk                                     | Workspace / agents                     | Always inspect via `find -L` / `realpath`.                |
