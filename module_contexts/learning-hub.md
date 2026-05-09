# Learning Hub Context

Learning Hub is the governance memory of the workspace. It records drift,
failures, hard cases, routing decisions, and improvement candidates.

## Owns

- architecture drift records
- boundary violation records
- routing decision records
- improvement queue
- NLP hard cases
- candidate promotion and rejection history
- governance summaries and learning events

## Primary Paths

- `Workbench/governance/system-learning-hub/`
- `System Learning Hub/`
- `Output/system_learning/`
- `Data/system_learning/`
- `routing_decision_record.template.yaml`
- `ROUTING_CONSTITUTION.md`
- `expert_activation_map.yaml`
- `expert_agent_roles.yaml`

`System Learning Hub/` is a compatibility symlink. Canonical source lives under
`Workbench/governance/system-learning-hub/`.

## Reads

- failed checks and boundary audit output
- routing decisions
- NLP candidate ledgers
- protocol promotion logs
- system status summaries
- events under `Output/system_learning/`

## Writes

- governance events
- improvement queue records
- routing decision records
- promoted governance memory under `Data/system_learning/`

## Must Not

- silently promote exploratory work
- replace Framework claims, Workbench behavior, or Harvester evidence
- treat audit findings as production inputs
- bypass owner modules when a fix belongs elsewhere

## Read First

- `MODULES.md`
- this file
- `ROUTING_CONSTITUTION.md`
- `routing_decision_record.template.yaml`
- relevant NLP protocol schemas when NLP governance is involved

## Escalate When

- a governance record requires code changes
- a boundary violation belongs to a specific module
- a hard case changes evaluation data
- a routing decision changes module ownership
- an audit finding should become a product, Framework, or Harvester task

Escalation usually goes to the owner module plus `protocols.md` if the handoff
shape changes.
