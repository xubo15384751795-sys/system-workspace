# Deformation Framework Context

The Deformation Framework owns structural theory and framework-specific
diagnosis. It consumes admitted evidence and publishes protocol-shaped outputs.

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

- `Structural Deformation Research System/src/core/`
- `Structural Deformation Research System/src/derivation/`
- `Structural Deformation Research System/src/dynamics/`
- `Structural Deformation Research System/src/operators/`
- `Structural Deformation Research System/src/diagnostics/`
- `Structural Deformation Research System/src/interpretation/`
- `Structural Deformation Research System/src/claims/`
- `Structural Deformation Research System/src/data_access/`
- `Structural Deformation Research System/tests/`
- `Structural Deformation Research System/wiki/`
- `Structural Deformation Research System/papers/`

## Reads

- admitted evidence from `Data/harvester/exports/`
- framework input protocols and manifests
- `protocols/evidence.schema.json`
- freshness and run configuration snapshots where applicable

## Writes

- run artifacts under `Output/deformation_runs/`
- framework diagnosis shaped by `protocols/framework_output.schema.json`
- manifests, summaries, evidence links, and next actions for Workbench
- framework-owned claims, wiki, and paper updates

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
