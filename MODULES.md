# Module Routing

This file is the first stop for humans and agents working in this workspace.
It keeps the IDE simple: open the single `System/` folder, then route each task
to the smallest owning module.

Default rule:

1. Start from one owning module.
2. Read that module's context file in `module_contexts/`.
3. Read the listed protocols before crossing module boundaries.
4. Inspect source files only after the owning module is clear.
5. Cross into another module's source only when an escalation rule triggers.

## Project Threads

These are the active project threads. A thread is a work lane with its own
owner, paths, and allowed communication points.

| Thread | Owns | Primary location | Context file |
|---|---|---|---|
| Workbench | User-facing commands, dashboards, current view, evidence views | `Workbench/`, `scripts/`, `Output/current/` | `module_contexts/workbench.md` |
| Deformation Framework | Structural theory, operators, diagnostics, dynamics, claims | `Structural Deformation Research System/` | `module_contexts/framework.md` |
| Harvester | Provider acquisition, provenance, data releases | `Workbench/data_providers/structural-risk-harvester/`, `Data/harvester/exports/` | `module_contexts/harvester.md` |
| Protocols | Schemas and contracts between modules | `protocols/`, `Workbench/contracts/workbench/` | `module_contexts/protocols.md` |
| Data and Output | Canonical truth, run artifacts, promotion boundary | `Data/`, `Output/` | `module_contexts/data-output.md` |
| Learning Hub | Governance memory, events, routing decisions, improvement queue | `Workbench/governance/system-learning-hub/`, `Output/system_learning/` | `module_contexts/learning-hub.md` |
| Agent Routing | Sparse activation, expert routing, workflow guards | `Workbench/agent_harness/`, `ROUTING_CONSTITUTION.md` | `module_contexts/agent-routing.md` |

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
- `Workbench/data_providers/structural-risk-harvester/`

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
- `Workbench/governance/system-learning-hub/`
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
- `expert_activation_map.yaml`
- `expert_agent_roles.yaml`

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
