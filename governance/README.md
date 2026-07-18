# Governance index

This directory is an implementation surface, not a reading list. Route a task
first and read only the returned module context:

```bash
python3 packages/workbench/agents/harness/entrypoints/routing_cli.py "<task>"
```

`governance_tiers.yaml` classifies every root artifact by enforcement shape.
The freeze check rejects unclassified artifacts, machine-shaped rules without
a code/test consumer, shape-6 growth above budget, or an always-read surface
larger than one page.

## Six shapes

| Rank | Shape | Human attention |
|---:|---|---|
| 1 | structural impossibility | none |
| 2 | executable invariant | only on violation |
| 3 | feedback loop | deviation only |
| 4 | precedent | on demand |
| 5 | principle | small constant |
| 6 | procedural rule | repeated memory |

Weight means attention demand, not file or line count. Machine registries may
grow with system variety; they must not become manual reading obligations.

## Artifact routing

- Execution: `daily_pipeline_registry.yaml`, `entrypoint_registry.yaml`
- Authority: `authority_registry.yaml`, `authority_graph_policy.yaml`,
  `output_routing_policy.yaml`
- Measurement: `canonical_proxy_spec.yaml`, `semantic_registry.json`,
  `proxy_observation_catalog.yaml`
- Live feedback: `capability_registry.yaml`, `data_request_registry.yaml`,
  `experimental_submission_registry.yaml`
- Case law: `architecture_*_decisions.md`, `routing_decisions/`
- History: `archive/`; it never supplies current authority

## Admission rule

State the maintained property before adding governance. Prefer structure,
invariant, loop, precedent, then compact principle. A procedural rule is
admissible only when none of those forms can maintain the property and it fits
the machine-enforced attention budget.
