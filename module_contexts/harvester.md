# Harvester Context

Harvester owns external data acquisition and evidence release publication. It
turns provider data into admitted evidence with provenance.

## Owns

- provider access and acquisition
- source registry
- raw-to-release normalization
- provenance and checksums
- freshness checks
- immutable release bundles
- source and data-quality notes

## Primary Paths

- `structural-risk-harvester/` — canonical source (git submodule at workspace root)
- `Structural Risk Harvester/` — compatibility symlink to the path above
- `Data/harvester/exports/`
- `configs/freshness_policy.yaml`
- Harvester tests inside the provider repo

The harvester is a **sibling repository**, not under `Workbench/data_providers/`.
That nested path appears in older docs only.

## Reads

- provider APIs and source files
- `configs/freshness_policy.yaml`
- release and evidence protocol schemas
- existing Harvester releases in `Data/harvester/exports/`

## Writes

- immutable release bundles under `Data/harvester/exports/`
- provider manifests
- provenance records
- checksums and source-quality records

## Promises

- We publish immutable releases with provenance, checksums, source identity and freshness state.
- Provider shape, completeness and date assertions live in this package's tests and quality code.
- A failed release check produces no admitted evidence side effect.
- When OpenBB is installed, registry routing prefers `openbb_*` providers
  (`HARVESTER_PREFER_OPENBB=auto|1|0`). Direct FRED may use `fredapi` when present;
  downstream `source_id` stays provider-native.

## Relies On

- Protocols promise versioned evidence and manifest shapes.
- Governance runtime promises failed admission cannot reach current publication.
- Consumers promise not to infer provider truth from sandbox or partial files.

## Must Not

- define Framework theory
- decide M / D / K / X meaning
- import Deformation Framework source
- write Workbench product dashboards directly
- silently overwrite released canonical evidence

## Read First

- `MODULES.md`
- this file
- `governance/repo_layout_map.md`
- `protocols/evidence.schema.json`
- `configs/freshness_policy.yaml`
- provider repo README and manifest docs

## Escalate When

- a release needs a new evidence field
- Workbench cannot render admitted evidence
- Deformation requires evidence that Harvester does not publish
- a source changes semantics or availability
- a sandbox/audit source is proposed for production input

Escalation usually goes to `protocols.md`, `workbench.md`, `framework.md`, or
`learning-hub.md`.
