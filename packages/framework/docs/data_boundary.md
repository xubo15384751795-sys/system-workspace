# Data Boundary

The current in-project data layer is legacy/frozen. Do not delete, relocate, or
fully migrate it yet.

## Transitional Rule

Existing project code may continue to read the current data layout. New data
ingestion should be implemented in the peer Harvester system at
`../Structural Risk Harvester` and exported as immutable bundles for this
project to consume through adapters.

```text
Structural Risk Harvester
  -> exports/latest/ or data/exports/latest/  # symlink to finalized release
     -> catalog.json
     -> manifests/<dataset_id>.manifest.json
     -> provenance/<dataset_id>.provenance.json
     -> data/<dataset_id>.<ext>
  -> Structural Deformation Research System
     -> src/data_access/harvester_adapter.py
```

## Main Project Boundary

The main project should consume exported bundles through `src/data_access/`.
It should not add new official-data connectors directly to proxy, benchmark,
diagnostic, research-corpus, report, UI, API, or script modules during the
transition.

Deformation is a Harvester artifact consumer. It does not own new acquisition,
publication, lineage, or provider logic for Harvester-sourced data.

Deformation remains responsible for structural runtime, proxy construction,
diagnostics, benchmark evaluation, case replay, UI/API/report rendering,
wiki/paper/claim governance, and a thin `src/data/gateway/` shim between
structural evidence intents and `src/data_access/`.

## Backend Selection

`data_backend` chooses the source boundary:

- `legacy`: read the current in-project data layout without changing it
- `harvester`: read exported bundles through Harvester's catalog and manifests

The default is `legacy` until migration is explicitly approved.

When `data_backend: harvester`, startup must load `catalog.json` successfully.
Missing catalogs, schema failures, missing data files, and sha256 mismatches are
fatal. Silent fallback to legacy is forbidden.

The required read sequence is:

```text
catalog.json -> manifest -> provenance/schema/hash check -> data file
```

No Deformation module may bypass the manifest and read an exported data file
directly.

## Required Source Tags

Benchmark, proxy, and corpus sources must remain tagged separately.

Suggested tags:

- `source_role=benchmark`
- `source_role=proxy_candidate`
- `source_role=corpus`
- `source_role=legacy`

Corpus documents are narrative evidence by default. They are not formal market
data and must not enter `M/D/K/X` proxy construction without a separate
structured dataset registration and manual approval.

## Forbidden During Transition

- Do not delete the existing data root.
- Do not rewrite current proxy, benchmark, or diagnostic logic to depend on the harvester.
- Do not import provider connectors from proxy modules.
- Do not mix benchmark, proxy, and corpus exports without role tags.
- Do not treat harvester corpus outputs as formal market data.
- Do not import `harvester` or `harvester.*` from Deformation.
- Do not bypass `src/data_access/harvester_adapter.py` to read Harvester `raw/`,
  `processed/`, `corpus/`, or `exports/*/data/` paths directly.
- Do not add new provider, downloader, external-source, or corpus acquisition
  logic under `src/data/`, `src/data/adapters/`, `src/data/gateway/`, or
  `src/research_corpus/providers/`.
- Do not move dataset/source notes, source-validation notebooks, data-agent
  prompts, or generated benchmark report artifacts back into Deformation.
