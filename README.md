# Verity

**An evidence-governed research kernel for reasoning under
incomplete, stale, conflicting, and uncertain information.**

Verity turns heterogeneous observations into auditable research objects:

```text
Source → Observation → Measurement → Evidence → Claim → Judgment
       → Admission / Promotion / Publication
```

It does not treat model output, retrieved data, or successful execution as
truth by default. Research objects become authoritative only through explicit
validation, admission, promotion, and publication boundaries.

| Name | Role |
|---|---|
| **Verity** | Product identity: the evidence-governed research kernel |
| `system-workspace` | This Git repository |
| `packages/*` | Implementation modules. They are not product names. |
| Structural Risk Workbench / Deformation / System Workspace | Historical names. See [workspace lineage](docs/history/workspace-lineage.md). |

The GitHub repository, Python distribution, and `packages/*` directories keep
their current names. Those are implementation identifiers, not a second product.

## Why Verity exists

Most research tooling solves one layer well:

- OpenBB provides data access.
- Dagster orchestrates computation.
- Qlib evaluates quantitative models.
- Agents search, generate, and analyze.

Verity governs what these outputs mean and when they may become trusted
research state.

## What it is

- A kernel for incomplete, stale, conflicting, and uncertain evidence.
- A publication boundary: only admitted, committed generations may change
  Current.
- A workspace that can run research objects from source acquisition through
  judgment without collapsing those objects into a dashboard or a model score.

## What it is not

- A data vendor, scheduler, or model zoo.
- A production research OS that is already proven on the scheduled path.
- A system in which `Data/` is automatically the runtime authority, or in
  which a green diagnostic run grants publication rights.

## Core principles

1. **One fact, one authority.** Runtime truth is owned by explicit
   authorities. Derived views are read-only projections.
2. **Durable data ≠ runtime authority.** `Data/` stores durable evidence.
   Current, admission, and publication are separate authorities.
3. **Unknown is a valid research result.** Missingness must not silently
   change measurement meaning.
4. **Models produce evidence, not truth.**
5. **Execution success does not imply publication authority.**
6. **Promotion is explicit.** Sandbox is isolated. Every artifact has a
   state.

The runtime rule is:

> one fact → one runtime authority → many read-only projections.

Current is not a copy of the latest Output. The live path is:

```text
Candidate Generation
  → PublishAdmission
  → PublishTransaction
  → COMMITTED
  → Output/current
```

Only an admitted, committed generation may modify Current. See
[authority and runtime matrix](docs/architecture/authority_runtime_matrix.md).

## Architecture

```text
Kernel          canonical IDs, admission, publication, current pointer
Data            Harvester releases, provenance, durable evidence
Orchestration   compiled plan, run outcome, Dagster/launchd execution
Capabilities    Workbench, Learning Hub, Framework, agents — replaceable
```

| Layer | Owns | Does not own |
|---|---|---|
| Kernel | Observation → Judgment lineage, `PublishAdmission`, `PublishTransaction`, Current | Provider transport, model scores, UI copy |
| Data / Harvester | Acquisition, provenance, immutable releases | Publication of Current |
| Orchestration | Compiled plan, `RunOutcome`, scheduled execution | Re-deciding admission |
| Replaceable capabilities | Interpretation, NLP, learning memory, agent routing | Runtime authority |

OpenBB is an **acquisition engine** inside Harvester
(`packages/harvester/src/harvester/providers/openbb_provider.py`). Downstream
consumers keep source IDs such as `fred` / `tiingo`; they do not depend on
OpenBB. Qlib and other experimental probes remain isolated until an explicit
routing decision and a Harvester release promote them.

## Project status

Verity is currently in **stabilization**.

The canonical evidence and authority contracts exist, but runtime ownership,
scheduled-path reproducibility, and long-run production evidence are still
being closed.

**Do not interpret a successful diagnostic or fixture run as production
readiness.** Dry-run, fixture, dirty-checkout, and old-artifact results remain
diagnostic evidence only. SYS-15, SYS-7, and SYS-19 still require clean
scheduled evidence.

| Area | Status |
|---|---|
| Architecture / governance | advanced |
| Canonical chain | implemented / migrating |
| Authority convergence | implementing |
| Dagster ownership | migrating |
| Measurement Kernel | incomplete |
| Clean scheduled evidence | incomplete |
| 14-day production proof | not complete |

## Quick start

Python 3.13 is the only supported runtime.

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv sync --locked --all-packages
./scripts/bootstrap.sh      # recreates compatibility aliases
```

There is no `.gitmodules` file. This is a monorepo under `packages/`.

Daily operator loop:

```bash
./sys check
./sys open
./sys next
./sys roadmap
```

`./sys roadmap` shows evidence-derived completion, blockers, and the next
eligible transition. Extra entrypoints live in
[workspace entrypoints](docs/operations/workspace-entrypoints.md).

## Repository Layout (monorepo workspace)

```text
System/                                 # system-workspace git repo
├── Data/                               # durable evidence (not a second runtime)
├── Output/                             # run packages, candidates, Current
├── configs/                            # canonical active configuration root
├── protocols/                          # cross-module JSON schemas
├── governance/                         # registries, freeze, routing decisions
├── system_runtime/                     # kernel: plan, outcome, admission, publish
├── scripts/                            # workspace entrypoints
├── tests/                              # workspace-level tests
├── packages/workbench/                 # operator surface, NLP, contracts, harness
├── packages/harvester/                 # providers, provenance, releases
├── packages/learning_hub/              # reliability and governance memory
├── packages/framework/                 # replaceable interpretation capability
└── packages/orchestration/             # Dagster/runtime orchestration
```

`Data/` and `Output/` are never committed. They are regenerated by Harvester
releases and governed runs. Compatibility aliases and historical paths are
recorded in [`governance/repo_layout_map.md`](governance/repo_layout_map.md).
`Config/` is retained only for the one-window source-registry compatibility
bridge; new configuration must be added under `configs/`.

## Integrations

| Tool | Role in Verity |
|---|---|
| OpenBB | Harvester acquisition engine. Not a sandbox experiment. Source IDs stay with the publisher. |
| Dagster | Execution substrate. Ownership is still migrating onto compiled-plan / `RunOutcome` authority. |
| Qlib | Isolated quantitative evaluation. Not a truth source. Promotion is explicit. |
| Agents | Search, generation, and analysis. They cannot publish Current. |

## Roadmap

Near-term closure is evidence, not features:

1. Finish canonical-chain producer/reader migration.
2. Converge remaining runtime facts onto the authority matrix.
3. Complete Dagster ownership so wrappers cannot re-decide truth.
4. Close Measurement Kernel gaps, including missingness semantics.
5. Produce clean scheduled evidence for SYS-15, SYS-7, and SYS-19.
6. Hold a 14-day production proof on the default path.

Plugin architecture and a Meta Framework sit after that proof. They must not
become a second identity while publication authority is still closing.

## Documentation

| Start here | File |
|---|---|
| Authority map | [`docs/architecture/authority_runtime_matrix.md`](docs/architecture/authority_runtime_matrix.md) |
| Canonical IDs | [`docs/architecture/canonical_id_contract.md`](docs/architecture/canonical_id_contract.md) |
| Layout (authoritative) | [`governance/repo_layout_map.md`](governance/repo_layout_map.md) |
| Operator entrypoints | [`docs/operations/workspace-entrypoints.md`](docs/operations/workspace-entrypoints.md) |
| Runtime clock policy | [`docs/operations/clock_strategy.md`](docs/operations/clock_strategy.md) |
| Historical names and migration | [`docs/history/workspace-lineage.md`](docs/history/workspace-lineage.md) |
| Archived architecture and handoff material | [`docs/history/`](docs/history/) |
| Product / framework boundary | [`PRODUCT_FRAMEWORK_BOUNDARY.md`](PRODUCT_FRAMEWORK_BOUNDARY.md) |
| Module routing | [`MODULES.md`](MODULES.md) |
| Change cadence | [`PACE.md`](PACE.md) |
