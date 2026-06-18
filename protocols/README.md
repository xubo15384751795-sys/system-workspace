# Protocols

Workbench protocols define how Product, Harvester, and Framework layers exchange data.

## Workbench Protocols

- `evidence.schema.json`: admitted evidence exposed to the Workbench
- `framework_output.schema.json`: framework diagnosis exposed to the Workbench
- `current_card.schema.json`: system status card (Output/current/status.json) — produced by build_next_actions.py

## NLP Boundary

Structural NLP — ingestion, chunking, extraction, variable mapping, candidate
export, promotion, and hard-case evaluation — is **not implemented or governed
in this directory**. That work belongs to the external library:

```text
Workbench/src/nlp/
```

### Protocol authority

All NLP-domain shapes are **owned and validated by the Structural NLP library**:

- `nlp_event_card.schema.json`
- `nlp_candidate_ledger.schema.json`
- `nlp_promotion_log.schema.json`

The copies under root `protocols/` are **compatibility mirrors** while protocol
files consolidate into the library project. Do not add new NLP semantics here;
change the library's protocol source instead (consolidation pending).

Consumers — Workbench CLI wrappers, Learning Hub, tests, harness tools — must
validate NLP outputs against the library's protocol definitions.

### Workbench product QA (cross-module handoff)

These two schemas remain at this layer for grounded evidence Q&A over admitted
local evidence and `Output/current/`:

- `nlp_query.schema.json`: user question over admitted/local evidence
- `nlp_answer.schema.json`: grounded answer with citations and limits

Implementation: `Workbench/src/workbench/nlp.py`. Optional modular LLM handoff
may include `prompt_sections` and `assembled_prompt`, backed by
`Workbench/contracts/workbench/agent_prompt_sections/` and `context_budget.yaml`.

### NLP governance rules (delegated)

The rules below are enforced by `Workbench/src/nlp/`, not re-defined here:

1. NLP tools answer over admitted evidence and current Workbench/Framework outputs.
2. They must not fetch external sources from Framework code or invent evidence.
3. All NLP extractions are candidates until reviewed — never auto-admitted to canonical.
4. Every event card must include evidence_quotes grounded in source text.
5. Variable mapping is rule-first with labeling-function votes; LLM may assist but not override.
6. Rejected or needs_revision cards are automatically appended to hard cases for evaluation.

When changing NLP behavior or protocol fields, start in `Workbench/src/nlp/` and
its protocol catalog. Root `protocols/nlp_*.schema.json` will follow in a later
consolidation pass.
