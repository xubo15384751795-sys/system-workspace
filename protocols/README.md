# Protocols

Workbench protocols define how Product, Harvester, and Framework layers exchange data.

## Workbench Protocols

- `evidence.schema.json`: admitted evidence exposed to the Workbench
- `framework_output.schema.json`: framework diagnosis exposed to the Workbench
- `current_card.schema.json`: user-facing current risk check

## NLP Protocols

- `nlp_query.schema.json`: user question over admitted/local evidence
- `nlp_answer.schema.json`: grounded answer with citations and limits
- `nlp_event_card.schema.json`: candidate structural event card with variable mapping, votes, and quote grounding
- `nlp_candidate_ledger.schema.json`: candidate ledger entry tracking every NLP export
- `nlp_promotion_log.schema.json`: promotion audit log recording all status transitions

### NLP Governance Rules

1. NLP tools answer over admitted evidence and current Workbench/Framework outputs.
2. They must not fetch external sources from Framework code or invent evidence.
3. All NLP extractions are candidates until reviewed — never auto-admitted to canonical.
4. Every event card must include evidence_quotes grounded in source text.
5. Variable mapping is rule-first with labeling-function votes; LLM may assist but not override.
6. Rejected or needs_revision cards are automatically appended to hard cases for evaluation.
7. Optional modular LLM handoff: `nlp_answer` may include `prompt_sections` and `assembled_prompt`, backed by `Workbench/contracts/workbench/agent_prompt_sections/` and `context_budget.yaml`.
