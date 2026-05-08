# Workbench Spec

The Workbench is a general-purpose evidence-to-diagnosis operating surface.
It does not own any specific framework.
Frameworks publish structured outputs through contracts.
The Workbench turns them into user-facing checks, evidence views, reports, and next actions.

## Product Responsibilities

- user commands
- current card
- evidence view
- report open
- provenance links
- system index
- next actions aggregation
- framework plugin registry
- grounded NLP / evidence QA over admitted evidence and current outputs

## Non-Goals

- define M/D/K/X
- fetch provider data directly
- hard-code Structural Deformation logic
- require users to learn framework terminology before basic use
- let NLP fetch external sources through Framework code
- let NLP invent evidence without citations

## Layer Boundary

```text
Workbench / Product
-> reads Harvester evidence contracts and Framework output contracts
-> renders check, evidence, explain, open, next, and doctor workflows

Harvester / Evidence
-> acquires external data
-> publishes admitted evidence releases with provenance

Frameworks
-> consume admitted evidence
-> publish diagnosis outputs through protocol files
```
