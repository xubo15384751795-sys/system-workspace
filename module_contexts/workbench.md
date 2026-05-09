# Workbench Context

Workbench is the product and tool surface. It turns protocol-shaped evidence
and framework outputs into user-facing checks, dashboards, reports, and next
actions.

## Owns

- user commands and cockpit workflows
- current card rendering
- evidence dashboard
- artifact navigator
- report and latest/current navigation
- workspace status and index utilities
- contract validation from the product side
- grounded NLP over admitted/local evidence and current outputs

## Primary Paths

- `Workbench/src/workbench/`
- `Workbench/tests/`
- `scripts/refresh_output_current.py`
- `scripts/build_benchmark_evidence_dashboard.py`
- `scripts/build_artifact_navigator.py`
- `scripts/validate_workbench_contract.py`
- `scripts/build_system_index.py`
- `scripts/list_latest.py`
- `scripts/system_status.py`
- `sys`
- `Output/current/`
- `Output/workbench/`

Top-level scripts are compatibility wrappers. Canonical Workbench source should
live under `Workbench/src/workbench/`.

## Reads

- `protocols/current_card.schema.json`
- `protocols/framework_output.schema.json`
- `protocols/evidence.schema.json`
- `protocols/nlp_query.schema.json`
- `protocols/nlp_answer.schema.json`
- `Data/system_index/`
- `Data/harvester/exports/`
- `Output/deformation_runs/`
- `Output/current/`

## Writes

- `Output/current/`
- `Output/workbench/`
- Workbench-facing reports, dashboards, and navigation artifacts

## Must Not

- import Deformation Framework source code
- define M / D / K / X semantics
- fetch external provider data directly
- promote run-local artifacts into canonical data without the promotion path
- hide missing public evidence silently

## Read First

- `MODULES.md`
- this file
- `WORKBENCH_SPEC.md`
- `PRODUCT_FRAMEWORK_BOUNDARY.md`
- relevant protocol schema files
- only then inspect `Workbench/src/workbench/`

## Escalate When

- a required protocol field is missing
- a Framework output violates `framework_output.schema.json`
- current card behavior needs new theoretical meaning
- evidence freshness depends on provider release internals
- a Workbench command needs to change artifact promotion rules

Escalation usually goes to `protocols.md`, `framework.md`, `harvester.md`, or
`data-output.md`.
