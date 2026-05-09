# Protocols Context

Protocols define the legal communication shapes between modules. They are the
shared language, not a place for module-specific implementation.

## Owns

- schema definitions
- contract compatibility
- examples and templates
- validation expectations
- cross-module field meanings
- producer/consumer handoff rules

## Primary Paths

- `protocols/`
- `protocols/README.md`
- `Workbench/contracts/workbench/`
- `contracts/`
- `FRAMEWORK_CONTRACT.md`
- `WORKBENCH_SPEC.md`
- `PRODUCT_FRAMEWORK_BOUNDARY.md`

`contracts/` is a compatibility symlink. Canonical Workbench contract source is
under `Workbench/contracts/workbench/`.

## Important Schemas

- `protocols/evidence.schema.json`
- `protocols/framework_output.schema.json`
- `protocols/current_card.schema.json`
- `protocols/nlp_query.schema.json`
- `protocols/nlp_answer.schema.json`
- `protocols/nlp_event_card.schema.json`
- `protocols/nlp_candidate_ledger.schema.json`
- `protocols/nlp_promotion_log.schema.json`

## Reads

- producer requirements from Harvester, Framework, Workbench, and Learning Hub
- consumer requirements from validators, dashboards, NLP, and reports

## Writes

- schemas
- protocol documentation
- compatibility examples
- validation fixtures where applicable

## Must Not

- contain provider acquisition logic
- contain Framework runtime logic
- contain product UI behavior
- become a dumping ground for unstable experimental fields

## Read First

- `MODULES.md`
- this file
- `protocols/README.md`
- the exact schema being changed
- the producer and consumer context files

## Escalate When

- a schema change requires producer code changes
- a schema change requires consumer code changes
- an optional field is becoming required
- a protocol begins encoding one module's internal implementation details
- compatibility with existing Data or Output artifacts may break

Schema changes should identify both sides: who writes the field and who reads
it.
