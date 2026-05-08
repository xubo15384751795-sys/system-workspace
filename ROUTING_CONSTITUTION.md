# Sparse Activation Routing Constitution

This workspace uses sparse activation for research, engineering, and review
work. The constitution is the always-active layer. Local expert protocols are
activated only when a task, artifact, event, or risk type requires them.

## Always-Active Rules

1. Evidence, code, wiki, papers, prompts, reports, and tests keep separate
   authority. No layer silently replaces another layer.
2. Global deny rules and hard pollution rules override every local expert
   protocol.
3. Deformation does not grow back into an acquisition system. Provider
   collection, source notes, provenance, and immutable export bundles belong to
   Harvester.
4. Research corpus material is not formal data unless a structured dataset
   manifest admits it.
5. Benchmarks and broad controls do not enter `Sigma_t` proxy core unless the
   claim registry explicitly changes their role.
6. Wiki or paper language cannot upgrade empirical claims beyond
   `wiki/claims/claim_registry.md`.
7. Paper text cannot cite diagnostic outputs without manifest, frequency
   policy, and no-lookahead evidence.
8. Execution and verification are separate phases. Referee, audit, and guardian
   protocols review outputs; they do not silently promote exploratory work.
9. Every expert activation needs an explicit reason, scope, and output artifact.
10. Failed expert runs still produce evidence: what was attempted, what failed,
    and what remains unresolved.
11. Routing decisions are observable learning inputs for System Learning Hub.

## Sparse Activation Discipline

Each task starts with the smallest sufficient expert set. Add experts only when
the task crosses a boundary, touches a protected artifact, raises a known risk,
or couples channels that must be reviewed together.

Local experts may inspect broad context, but their authority is scoped to the
activation reason. Exploratory experts may propose outputs, but promotion into
code, claims, wiki, papers, or release artifacts requires the relevant owner or
verification protocol.

## Required Routing Artifact

For non-trivial tasks, create or update a routing decision record using
`routing_decision_record.template.yaml`. Store concrete records under a run,
report, or Learning Hub output directory that matches the work.

Minimum fields:

- task id or date
- artifacts touched
- experts activated
- reason and scope for each activation
- experts intentionally not activated
- verification performed or failed
- final auditable outputs

