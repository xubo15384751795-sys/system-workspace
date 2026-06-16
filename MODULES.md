# Module Routing

This file is the first stop for humans and agents working in this workspace.
It keeps the IDE simple: open the single `System/` folder, then route each task
to the smallest owning module.

**Layout / git policy:** `governance/repo_layout_map.md`, `governance/git_workspace_policy.md`

Default rule:

1. Start from one owning module.
2. Read that module's context file in `module_contexts/`.
3. Read the listed protocols before crossing module boundaries.
4. Inspect source files only after the owning module is clear.
5. Cross into another module's source only when an escalation rule triggers.

## Project Threads

These are the active project threads. A thread is a work lane with its own
owner, paths, and allowed communication points.

**Status legend:** See `governance/capability_registry.yaml` for full status enum and details.
**Architecture authority:** `governance/architecture_reality_decisions.md` — constitution-layer decisions override historical docs and audit reports.

| Thread | Status | Owns | Primary location | Context file | Tests |
|---|---|---|---|---|---|
| Workbench | `CANONICAL` | User-facing commands, dashboards, current view, evidence views | `Workbench/`, `scripts/`, `Output/current/` | `module_contexts/workbench.md` | 14 |
| Deformation Framework | `ACTIVE_PARTIAL` | Structural theory, operators, diagnostics, dynamics, claims | `Structural Deformation Research System/` | `module_contexts/framework.md` | 15 |
| Harvester | `CANONICAL` | Provider acquisition, provenance, data releases | `structural-risk-harvester/`, `Data/harvester/exports/` | `module_contexts/harvester.md` | 12 |
| Protocols | `CANONICAL` | Schemas and contracts between modules | `protocols/`, `Workbench/contracts/workbench/` | `module_contexts/protocols.md` | — |
| Data and Output | `ACTIVE_PARTIAL` | Canonical truth, run artifacts, promotion boundary | `Data/`, `Output/` | `module_contexts/data-output.md` | — |
| Learning Hub | `ACTIVE_PARTIAL` | Governance memory, events, routing decisions, improvement queue | `system-learning-hub/`, `Data/system_learning/`, `Output/system_learning/` | `module_contexts/learning-hub.md` | 7 |
| Agent Routing | `SHADOW_ACTIVE` | Sparse activation, expert routing, workflow guards; diagnostics only | `Workbench/agents/harness/`, `ROUTING_CONSTITUTION.md` | `module_contexts/agent-routing.md` | — |
| CaseLab Context | `ACTIVE_PARTIAL` | Entity DNA, regime context, meaning resolver, note retrieval | `caselab_context/`, `caselab_runtime/`, Paper `90_Admin/Context/` | `module_contexts/caselab-context.md` | — |
| NLP Pipeline | `ACTIVE_PARTIAL` | Event extraction, case similarity, narrative drift | `Workbench/src/nlp/` | — | 3 |
| ML Signals | `REAL_EXPERIMENTAL` | Regime detection, factor model, graph embeddings | `Workbench/src/ml/` | — | 3 |
| Backtest Lens | `REAL_EXPERIMENTAL` | Market feedback, historical replay evaluation | `ExternalTools/`, `scripts/run_historical_replay.py` | — | — |
| Qlib Benchmark | `REAL_EXPERIMENTAL` | Isolated benchmark runner, alpha metrics | `ExternalTools/qlib_benchmark_runner/` | — | 1 |
| Research Terminal | `PAPER_RETAIN` | Embedded research terminal | `research_terminal/` | — | — |

## Dependency Rule

Modules do not depend on each other's source code by default. They communicate
through protocols and published artifacts.

Allowed shape:

```text
Harvester -> Protocols -> Data
Deformation Framework -> Protocols -> Output
Workbench -> Protocols -> Data / Output
Learning Hub -> Protocols -> Data / Output
Agent Routing -> module_contexts / routing rules
```

Avoid these shapes unless the task is explicitly a boundary migration:

```text
Workbench -> Deformation source
Deformation Framework -> Workbench source
Harvester -> Deformation source
Deformation Framework -> Harvester source
```

## Workbench

Use this thread when the task mentions:

- `sys`
- current card
- dashboard
- evidence view
- artifact navigator
- next actions
- report opening or user-facing run navigation
- contract validation from the product surface

Read first:

- `module_contexts/workbench.md`
- `protocols/current_card.schema.json`
- `protocols/framework_output.schema.json`
- `protocols/evidence.schema.json`
- `Workbench/src/workbench/`

For structural NLP (extraction, event cards, candidate ledger, promotion):

- `Workbench/src/nlp/` — canonical implementation and NLP-domain protocol owner
- root `protocols/nlp_*.schema.json` — compatibility mirrors only

Do not read first:

- `Structural Deformation Research System/src/core/`
- `Structural Deformation Research System/src/dynamics/`
- provider acquisition internals

## Deformation Framework

Use this thread when the task mentions:

- M / D / K / X
- Sigma
- morphology
- operators
- diagnostics
- dynamics
- structural replay
- theory, interpretation, claims, wiki, or papers

Read first:

- `module_contexts/framework.md`
- `protocols/framework_output.schema.json`
- `Structural Deformation Research System/src/core/`
- `Structural Deformation Research System/src/diagnostics/`
- `Structural Deformation Research System/src/operators/`

Do not read first:

- `Workbench/src/workbench/`
- Harvester provider code
- generic dashboard renderers

## Harvester

Use this thread when the task mentions:

- source data
- provider
- FRED, SEC, Treasury, OpenBB acquisition, or similar sources
- data release
- provenance
- freshness
- checksums or source registry

Read first:

- `module_contexts/harvester.md`
- `protocols/evidence.schema.json`
- `configs/freshness_policy.yaml`
- `structural-risk-harvester/`

Do not read first:

- Deformation dynamics or operators
- Workbench dashboard internals

## Protocols

Use this thread when the task mentions:

- schema
- contract
- compatibility
- field shape
- validation
- cross-module exchange
- changing what one module publishes or another consumes

Read first:

- `module_contexts/protocols.md`
- `protocols/README.md`
- `protocols/*.schema.json`
- `Workbench/contracts/workbench/`

Escalate after:

- identifying which producer writes the field
- identifying which consumer reads the field
- updating tests or validators for the changed contract

## Data and Output

Use this thread when the task mentions:

- canonical data
- snapshots
- promotion
- latest symlink
- run artifacts
- `Output/current/`
- `Data/system_index/`
- artifact state

Read first:

- `module_contexts/data-output.md`
- `README.md`
- `FOLDER_OWNERSHIP.md`
- `scripts/list_latest.py`
- `scripts/promote_snapshot.py`

## Learning Hub

Use this thread when the task mentions:

- governance memory
- architecture drift
- boundary violation
- hard cases
- improvement queue
- routing decision records
- NLP promotion or rejection history

Read first:

- `module_contexts/learning-hub.md`
- `ROUTING_CONSTITUTION.md`
- `routing_decision_record.template.yaml`
- `system-learning-hub/`
- `Data/system_learning/`
- `Output/system_learning/`

## Agent Routing

Use this thread when the task mentions:

- agent context
- sparse activation
- expert routing
- task routing
- workflow guard
- reducing repeated project-wide reads

Read first:

- `module_contexts/agent-routing.md`
- `MODULES.md`
- `ROUTING_CONSTITUTION.md`

## External Tool Integration

Three external tools operate under strict module_authority boundaries:

| Tool | Allowed Module | Routing Decisions |
|---|---|---|
| OpenBB | Harvester only (ACQUIRE_VIA_OPENBB) | `2026-05-17-openbb-acquisition-consolidation.yaml` |
| GluonTS | Workbench + Deformation (add-alongside, PROXY_PROBABILISTIC) | `2026-05-17-gluonts-probabilistic-forecasting.yaml` |
| Qlib | External sandbox executor only (RUN_ISOLATED_BENCHMARK) | `2026-05-17-qlib-executor-promotion.yaml` |

Boundary rules:
- OpenBB: Forbidden outside `structural-risk-harvester/`. Enforced by boundary test.
- GluonTS: Outputs must pass through `semantic_registry` (PROXY_PROBABILISTIC, semantic_distance=2). Cannot support structural claims without constitution validation.
- Qlib: Runner communicates only via `sandbox_input/` (read) and `qlib_output/` (write). Forbidden from `DEFINE_STRUCTURAL_TRUTH`, `WRITE_CORE_PROXY`, `MODIFY_DEFORMATION_OUTPUT`.

Protocol integration decision: `2026-05-17-catalog-protocol-unification.yaml`
Legacy freeze decision: `2026-05-17-legacy-acquisition-freeze.yaml`

## Legacy DataHub Freeze (F.1)

The legacy DataHub acquisition layer (`src/data/gateway/data_hub.py`, `src/data/adapters/`)
is frozen by default. Production runs must use the Harvester-backed DataHubLite.
Legacy DataHub can be re-enabled with `ALLOW_LEGACY_DATAHUB=1` for:
- Legacy replay
- Migration testing
- Emergency fallback

Mock mode (`use_mock=True`) is exempt from the freeze to preserve test compatibility.

## Submodule Structure (Transitional)

The current 4-submodule structure (Workbench, Deformation Framework, Harvester, Learning Hub)
is **transitional, not strategic**. Buffer period: 30-45 days from 2026-06-16.

Buffer period goals:
1. Clear dirty submodule state.
2. Unify test entry points.
3. Unify Python version and dependency strategy.
4. Clarify migration path.
5. Final target: single-repo workspace with `packages/` directory.

See `governance/architecture_reality_decisions.md` §9 for details.

## Escalation Rules

Escalate from one thread to another only when:

- a protocol field is missing or ambiguous
- the producer and consumer disagree about a schema
- tests show a cross-module failure
- a task explicitly changes module ownership
- a generated artifact cannot be explained from its owning module
- a governance record requires multi-module evidence

When escalation happens, keep the original owning module visible and state the
reason for crossing the boundary.
