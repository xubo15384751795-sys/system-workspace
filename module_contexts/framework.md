# Deformation v1 Evidence Archive Context

Deformation v1 is an evidence archive for a falsified operational host theory.
It preserves source, tests, papers, and replay evidence, but has no authority to
execute in the default path, publish current state, or promote artifacts.

The binding decision is
`governance/routing_decisions/2026-07-18-deformation-v1-estate-settlement.yaml`.

## Owns

- M / D / K / X semantics
- Sigma and morphology
- structural primitive state
- event operators and non-commutativity
- dynamics and diagnostics
- framework-specific replay, validation, and scenario labs
- structural interpretation
- claims, wiki, and papers

## Primary Paths

- `packages/framework_v1_archive/src/core/`
- `packages/framework_v1_archive/src/derivation/`
- `packages/framework_v1_archive/src/dynamics/`
- `packages/framework_v1_archive/src/operators/`
- `packages/framework_v1_archive/src/diagnostics/`
- `packages/framework_v1_archive/src/interpretation/`
- `packages/framework_v1_archive/src/claims/`
- `packages/framework_v1_archive/src/data_access/`
- `packages/framework_v1_archive/tests/`
- `packages/framework_v1_archive/wiki/`
- `packages/framework_v1_archive/papers/`

## Reads

- admitted evidence from `Data/harvester/exports/`
- framework input protocols and manifests
- `protocols/evidence.schema.json`
- freshness and run configuration snapshots where applicable

## Archived historical writes

- historical run artifacts under `Output/deformation_runs/`
- historical claims, wiki, papers, and falsification evidence

No new authoritative writes are permitted.

## Archive promises

- Evidence remains reproducible and is never silently deleted.
- Archived code cannot write `Output/current/`, judgment, trade, or promotion artifacts.
- No patch may restore v1 operational authority.
- Surviving tools and candidates receive new identities and no inherited permissions.

## Relies On

- Harvester promises admitted, immutable and provenance-bearing evidence.
- Protocols promise versioned handoff shapes during migrations.
- Workbench promises to display blockers and validity limits without changing their meaning.

## Must Not

- grow back into a provider acquisition system
- fetch external provider data directly
- import Workbench product code
- own generic dashboard, report navigation, or artifact browser workflows
- encode Harvester provider internals
- promote Output artifacts into Data without the explicit promotion path

## Read First

- `MODULES.md`
- this file
- `FRAMEWORK_CONTRACT.md`
- `PRODUCT_FRAMEWORK_BOUNDARY.md`
- `protocols/framework_output.schema.json`
- `protocols/evidence.schema.json`
- then the smallest relevant Framework source folder

## Escalate When

- Workbench needs a new output field
- admitted evidence is missing or malformed
- a provider source must be added or changed
- a claim changes empirical status
- a run artifact should become canonical Data
- a generic product workflow is being added

Escalation usually goes to `protocols.md`, `harvester.md`, `data-output.md`, or
`workbench.md`.
