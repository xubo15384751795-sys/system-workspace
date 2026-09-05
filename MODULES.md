# Module Routing

This is an on-demand ownership map, not required reading. The task router
selects the smallest owning module and returns one local context file:

```bash
python3 packages/workbench/agents/harness/entrypoints/routing_cli.py "<task>"
```

Architecture and migration decisions under `governance/` are precedent. Live
authority comes from machine registries, runtime gates, schemas, and tests.

## Project Threads

These are the active project threads. A thread is a work lane with its own
owner, paths, and allowed communication points.

**Status legend:** See `governance/capability_registry.yaml` for full status enum and details.
**Architecture precedent:** `governance/architecture_reality_decisions.md` records why the current boundaries exist.

| Thread | Status | Owns | Primary location | Context file | Tests |
|---|---|---|---|---|---|
| Workbench | `CANONICAL` | User-facing commands, dashboards, current view, evidence views, Streamlit UI | `packages/workbench/`, domain entrypoints under `scripts/`, `Output/current/` | `module_contexts/workbench.md` | 14 |
| Orchestration | `CANONICAL` | Pipeline compilation/execution, Dagster daily/refresh jobs, Pandera/GE quality adapters, DVC promote helpers, optional Sentry/Datadog notify sinks | `packages/orchestration/`, `scripts/daily_run.py` compatibility entrypoint, `system_runtime/observability.py` | `module_contexts/orchestration.md` | 8 |
| Deformation v1 evidence archive | `ARCHIVED_FALSIFIED` | Falsified host-theory evidence, reproducibility, postmortem | `packages/framework_v1_archive/` | `module_contexts/framework.md` | archive-only |
| Neutral Macro Pressure | `ACTIVE_PARTIAL` | Funding-mismatch and market-constraint gauges | `scripts/neutral_pressure_measurement.py`, `docs/measurements/` | `module_contexts/workbench.md` | requalification |
| Harvester | `CANONICAL` | Provider acquisition, provenance, data releases | `packages/harvester/`, `Data/harvester/exports/` | `module_contexts/harvester.md` | 12 |
| Protocols | `CANONICAL` | Schemas and contracts between modules | `protocols/`, `packages/workbench/contracts/workbench/` | `module_contexts/protocols.md` | — |
| Data and Output | `ACTIVE_PARTIAL` | Canonical truth, run artifacts, promotion boundary, DVC pointers | `Data/`, `Output/` | `module_contexts/data-output.md` | — |
| Learning Hub | `ACTIVE_PARTIAL` | Governance memory, events, routing decisions, improvement queue | `packages/learning_hub/`, `Data/system_learning/`, `Output/system_learning/` | `module_contexts/learning-hub.md` | 7 |
| Agent Routing | `ACTIVE_PARTIAL` | Sparse activation, expert routing, workflow guards; diagnostics only | `packages/workbench/agents/harness/`, `ROUTING_CONSTITUTION.md` | `module_contexts/agent-routing.md` | — |
| CaseLab Context | `ACTIVE_PARTIAL` | Entity DNA, regime context, meaning resolver, note retrieval (LanceDB ANN) | `caselab_context/`, `caselab_runtime/`, Paper `/90_Admin/Context/` (external, under paper_root) | `module_contexts/caselab-context.md` | — |
| NLP Pipeline | `ACTIVE_PARTIAL` | Event extraction, case similarity, narrative drift (top-level `nlp`; framework translator is `framework_nlp`) | `packages/workbench/src/nlp/` | — | 3 |
| ML Signals | `REAL_EXPERIMENTAL` | Regime detection, factor model, graph embeddings | `packages/workbench/src/ml/` | — | 3 |
| Funding Endogenous Boundary v2 | `REAL_EXPERIMENTAL` | X stock, absorption capacity, non-commutativity candidates under preregistration | `scripts/`, `Output/validation/` | — | validation-only |
| Backtest Lens | `REAL_EXPERIMENTAL` | Market feedback, historical replay evaluation | `ExternalTools/` | — | — |
| Qlib Benchmark | `REAL_EXPERIMENTAL` | Isolated benchmark runner (workflow API), alpha metrics | `ExternalTools/qlib_benchmark_runner/` | — | 1 |
| Research Terminal | `ARCHIVED` | Legacy HTML research terminal (replaced by Streamlit) | `governance/archive/research_terminal/` | — | — |
| Visualization demos | `ARCHIVED` | Legacy Plotly/ECharts demos (replaced by Streamlit) | `governance/archive/Visualization/` | — | — |

### `scripts/` boundary

`scripts/` is an integration surface, not an ownership thread. Shared pipeline
mechanism belongs to `packages/orchestration/orchestration/`; the legacy
`scripts/_pipeline_runner.py`, `scripts/_pipeline_dag.py`, and
`scripts/_daily_run_sequence.py` paths are compatibility imports only.
`scripts/daily_run.py` remains the documented default entrypoint until the
launchd/Dagster cutover is separately approved. New shared runner, DAG, or
sequence logic must not be added under `scripts/`; domain-specific scripts
must route to their owning thread.

## Dependency Rule

Modules do not depend on each other's source code by default. They communicate
through protocols and published artifacts.

Allowed shape:

```text
Harvester -> Protocols -> Data
Neutral Macro Pressure -> Protocols -> Output
Workbench -> Protocols -> Data / Output
Learning Hub -> Protocols -> Data / Output
Agent Routing -> module_contexts / routing rules
```

Avoid these shapes unless the task is explicitly a boundary migration:

```text
Workbench -> archived Deformation source
Archived Deformation -> Workbench source
Harvester -> archived Deformation source
Archived Deformation -> Harvester source
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
- `packages/workbench/src/workbench/`

For structural NLP (extraction, event cards, candidate ledger, promotion):

- `packages/workbench/src/nlp/` — canonical implementation and NLP-domain protocol owner
- root `protocols/nlp_*.schema.json` — compatibility mirrors only

Do not read first:

- `packages/framework_v1_archive/src/core/`
- `packages/framework_v1_archive/src/dynamics/`
- provider acquisition internals

## Deformation v1 Evidence Archive

This thread is not a live module. Open `module_contexts/framework.md` only
when the task explicitly asks to reproduce v1 falsified evidence or to read
the estate settlement.

When M / D / K / X appear as historical symbols, first reads are the estate
record and current measurements, not archived implementation source:

- `governance/routing_decisions/2026-07-18-deformation-v1-estate-settlement.yaml`
- `docs/measurements/`

Do not read first:

- `packages/framework_v1_archive/src/core/`
- `packages/framework_v1_archive/src/dynamics/`
- `packages/framework_v1_archive/src/operators/`
- `packages/workbench/src/workbench/`
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
- `packages/harvester/`

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
- `packages/workbench/contracts/workbench/`

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
- `packages/learning_hub/`
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

External-tool permissions, legacy freezes, and cross-module escalation are
compiled into registries, boundary tests, archive guards, and the task router.
Consult routing decisions only when the current case matches their subject.
