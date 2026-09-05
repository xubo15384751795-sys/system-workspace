# Product / Framework Boundary

This workspace separates user-facing tools from framework-specific theory.

## Layer Model

```text
Harvester
  -> Protocols
  -> Neutral Macro Pressure / Workbench
```

The Product / Workbench layer is the neutral operating surface. It should be
useful even when the user does not accept, understand, or use archived
Deformation v1 theory.

## Product / Workbench

Owns generic user workflows:

- benchmark and evidence dashboards
- run cockpit and current/latest navigation
- report rendering and artifact navigation
- data freshness, provenance, manifest, and health display
- commands that answer "what should I open now?"

Product tools may read framework outputs only through protocol-shaped files
such as `run_manifest.json`, `artifacts.json`, `dashboard_snapshot.json`, and
Workbench `model_run` records.

Product tools must not require framework concepts for basic use.

## Protocol / Contracts

Owns the shapes that connect layers:

- data provider release manifests
- evidence panel records
- model run records
- snapshot records
- report artifact records
- governance event records

Protocols are the only coupling point between Product, Frameworks, and Data
Providers. Layers should not import each other to discover meaning.

## Data Consumption vs Audit

The production evidence path and the secondary audit path are separate:

```text
Production consumption:
  OpenBB or other external providers
    -> Harvester acquisition / normalization / provenance
    -> Data/harvester/exports/<release_id>/
    -> Protocols
    -> Neutral Macro Pressure / Workbench
```

### Historical consumption (archived)

Deformation v1 historically consumed admitted Harvester releases and wrote
run output. That path is an evidence archive only. It is not the production
chain.

```text
Historical consumption (archived):
  Harvester admitted release
    -> archived Deformation data_access adapter
    -> archived Deformation run output

Secondary audit:
  OpenBB raw or sandbox probe data
    -> Workbench audit comparison against archived Deformation outputs
    -> Learning Hub event / ledger / improvement queue
```

Archived Deformation must not negotiate with, import, or directly understand OpenBB.
OpenBB data can be used to audit archived Deformation outputs only from the Workbench /
Learning Hub side. Audit findings may create Learning Hub records and proposed
improvements; they do not become archived Deformation input unless Harvester publishes a
finalized release.

## Data Providers

Own source acquisition and release publication:

- raw source access
- source registry
- manifest and catalog
- provenance and checksum validation
- immutable release bundles

Data Providers must not know framework theory. A provider may publish NFCI,
VIX, MOVE, STLFSI, OFR FSI, credit spreads, or other evidence; it does not
decide what those signals mean inside a framework.

## Current Ownership

```text
Product / Workbench:
  ./sys
  packages/workbench/
  packages/workbench/src/workbench/current.py
  packages/workbench/src/workbench/evidence_dashboard.py
  packages/workbench/src/workbench/artifact_navigator.py
  packages/workbench/src/workbench/contract_validator.py
  packages/workbench/src/workbench/workspace/
  packages/workbench/contracts/workbench/
  packages/workbench/contracts/workbench/
  packages/harvester/
  packages/workbench/agents/harness/
  packages/learning_hub/
  scripts/refresh_output_current.py (compatibility wrapper)
  scripts/build_benchmark_evidence_dashboard.py (compatibility wrapper)
  scripts/build_artifact_navigator.py (compatibility wrapper)
  scripts/validate_workbench_contract.py (compatibility wrapper)
  Output/current/
  Output/workbench/

Protocol / Contracts:
  packages/workbench/contracts/workbench/
  contracts/workbench/ (compatibility symlink)
  Data/system_index/
  run_manifest.json
  artifacts.json
  dashboard_snapshot.json

Historical consumption (archived):
  packages/framework_v1_archive/src/proxies/
  packages/framework_v1_archive/src/derivation/
  packages/framework_v1_archive/src/operators/
  packages/framework_v1_archive/src/diagnostics/
  packages/framework_v1_archive/src/dynamics/
  packages/framework_v1_archive/src/interpretation/
  packages/framework_v1_archive/wiki/
  packages/framework_v1_archive/papers/

Data Provider:
  packages/harvester/
  Structural Risk Harvester/ (compatibility symlink)
  Data/harvester/exports/

Governance Memory:
  packages/learning_hub/
  System Learning Hub/ (compatibility symlink)
  Data/system_learning/
  Output/system_learning/
```

## Rules

1. Product tools provide a low-friction basic view before framework-specific
   interpretation.
2. Product tools do not import framework packages.
3. Framework code does not import data provider packages.
4. Data providers do not import framework packages or encode framework theory.
5. Report renderers may display framework payloads, but their artifact protocol
   stays generic.
6. Missing public evidence is shown as missing, not silently hidden.
7. Secondary OpenBB audits are observe-only: OpenBB output **must not** be
   consumed by Deformation directly. These audits compare raw/provider evidence
   to archived Deformation outputs and write Learning Hub records; they must
   not become model input.
8. `Output/current/` remains a pointer and cockpit layer; it does not copy large
   report artifacts.
9. Product source code lives in `packages/workbench/`. Top-level `scripts/` entries for
   Workbench behavior must be thin wrappers.
10. Data Provider and Agent Harness source are separate nested repos or
    Workbench subfolders. Human-readable symlinks at workspace root are
    compatibility aliases only.
11. Governance memory lives in `packages/learning_hub/` with canonical artifacts
    under `Data/system_learning/` and `Output/system_learning/`.
    Top-level `System Learning Hub` and `contracts` are compatibility symlinks.
