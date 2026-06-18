# Agent Routing Context

Agent Routing controls how humans and agents select context. Its purpose is to
reduce repeated project-wide reads without hiding important boundaries.

## Owns

- sparse activation rules
- expert routing
- task-to-module mapping
- workflow guards
- context-pack maintenance
- routing decision templates
- agent-facing policies and hooks

## Primary Paths

- `MODULES.md`
- `module_contexts/`
- `ROUTING_CONSTITUTION.md`
- `routing_decision_record.template.yaml`
- `Workbench/agents/harness/`
- `Structural Research Harness/`

`Structural Research Harness/` is a compatibility symlink. Canonical source
lives under `Workbench/agents/harness/`.

## Reads

- module context files
- routing constitution
- expert activation map
- prior routing decision records
- governance events from Learning Hub

## Writes

- routing guidance
- agent harness policies and hooks
- routing decision records for non-trivial cross-module tasks
- updates to `MODULES.md` and `module_contexts/`

## Must Not

- make every task cross-module by default
- activate experts without a reason and scope
- change module ownership casually
- let convenience override protocol boundaries
- force humans to open multiple IDE roots for routine work

## Read First

- `MODULES.md`
- this file
- `ROUTING_CONSTITUTION.md`
- relevant module context file

## Escalate When

- a task cannot be owned by one module
- a module context is missing or misleading
- routing rules conflict with folder ownership
- repeated tasks still require project-wide reads
- an expert activation should create a governance record

## Operating Rule

For normal work:

```text
Open one IDE folder: /Users/a1/System
Read one routing file: MODULES.md
Activate one module context: module_contexts/<module>.md
Add protocols and artifacts as needed
Cross source boundaries only with an explicit reason
```

For fuzzy or non-trivial requests, first ask the harness router for a structured
decision:

```text
system tools run routing.route_task task="<user task>" --mode explore --json
```

The router returns the owning module, context file, recommended mode, expert
activations, escalation reasons, and whether a routing decision record is
required. Treat that output as the starting point; it does not override the
constitution or hard boundary rules.

To turn the routing result into a ToolSpec-bound checklist, use:

```text
system tools run routing.create_task_plan task="<user task>" --mode explore --json
```

## Work Protocol

Every Agent-initiated code change must follow the work protocol defined in
`governance/system_constitution.yaml → agent_work_protocol`.

Before editing any file, the Agent must declare:

| Field | Source |
|-------|--------|
| owner module | `governance/capability_registry.yaml` |
| touched paths | target files |
| authority level | module's `allowed_claims` in registry |
| expected artifact | what the change produces |
| verification command | how to confirm it works |
| affects core judgment | yes/no — if yes, extra gates apply |

Template: `module_contexts/agent_work_protocol.template.yaml`

Hard rules:

- No new root scripts unless thin wrapper (see `governance/redundancy_budget.yaml`)
- No new governance files unless explicitly approved (see `governance/governance_freeze_manifest.yaml`)
- Schema changes: protocol → producer → consumer
- Experiment outputs default to `research_only`
- Cross-module changes require explicit reason and routing decision record

Each plan step names its phase, owner, mode, risk category, verification rule,
and registered ToolSpec candidates. A step marked `missing_tool_spec` is blocked
planning debt; it is not permission to run a free-form script.

To audit which existing workspace actions still need ToolSpec wrappers, use:

```text
system tools run routing.tool_coverage_audit --mode explore --json
```

Treat critical and high-priority `missing_tool_spec` findings as runtime
governance debt before agents rely on those underlying scripts.
