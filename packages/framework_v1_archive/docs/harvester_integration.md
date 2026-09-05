# Harvester Integration

Deformation consumes Harvester output only through `src/data_access/`.
No Deformation module imports `harvester`, and no module reads Harvester raw,
processed, corpus, or export data files directly.

Harvester is a peer system at `../Structural Risk Harvester`. Deformation is a
consumer, not an owner of Harvester data or provider code.

Harvester produces verifiable data artifacts. Deformation consumes those
artifacts for structural-risk research, interpretation, modeling, replay,
claim-guarding, reports, UI, and API outputs.

## Configuration

```yaml
data_backend: legacy   # legacy | harvester
harvester:
  root: ../Structural Risk Harvester
  require_finalized: true
```

The adapter accepts the Harvester repository root. It reads the active release
from `exports/latest` when present, and from `data/exports/latest` for the
current peer repository layout.

`data_backend: legacy` remains the default until migration is explicitly
approved. In legacy mode the existing in-project data layer remains readable and
unchanged, but the router emits a deprecation warning.

## Load Sequence

1. Read `catalog.json` from the active release.
2. Validate `catalog.json` against Harvester's `contracts/catalog.schema.json`.
3. Select a dataset entry by `dataset_id`.
4. Read and validate the dataset manifest against
   `contracts/dataset_manifest.schema.json`.
5. Read and validate the provenance record against
   `contracts/provenance.schema.json`.
6. Verify `byte_size` and `sha256` before loading the data file.
7. Load the file into a dataframe.

Any missing catalog, schema mismatch, unsafe relative path, missing data file,
or hash mismatch raises an exception. There is no silent fallback to legacy.

Research modules must not skip to step 6. Data files are only readable after the
catalog, manifest, provenance, schema, and hash checks have succeeded inside
`src/data_access/harvester_adapter.py`.

## Public Adapter Surface

`HarvesterAdapter` exposes:

- `list_datasets()`
- `get_manifest(name)`
- `load_dataset(name, as_of=None, vintage=None)`

`as_of` filters against the manifest's `as_of_date`; `vintage` filters against
`vintage_date`. A mismatch raises rather than scanning raw files or guessing a
nearby dataset.

Business modules should enter through the router:

```python
from src.data_access import create_data_adapter

adapter = create_data_adapter(config)
dataset = adapter.load_dataset("benchmark_panel")
```

Modules outside `src/data_access/` should not know whether the backing source
is legacy or Harvester.

## Dataset Requirements

Deformation's requested Harvester contracts are listed in
`docs/harvester_dataset_requirements.md`. Harvester manifests prove artifact
integrity; Deformation's requirement sheet defines the semantic contract that
research modules expect after loading a manifest-backed dataset.

Column-name, table-name, and resampling differences should be handled in a
Deformation semantic adapter layer behind `src/data_access/`, not repeated in
each proxy, benchmark, diagnostic, replay, or UI module.

## Boundary Rules

- Deformation may reference Harvester schema files by path.
- Deformation may read `catalog.json`, manifests, provenance, and declared data
  files through `src/data_access/harvester_adapter.py`.
- Deformation must not import `harvester`.
- Deformation must not read Harvester `raw/`, `processed/`, `corpus/`, or
  `exports/*/data/` paths directly.
- New providers, downloaders, external-source fetchers, and corpus acquisition
  scripts belong in Risk Harvester, not in `src/data/`,
  `src/data/adapters/`, `src/data/gateway/`, or
  `src/research_corpus/providers/`.
- `legacy_adapter.py` exists only for compatibility with old tests, pipelines,
  and layouts. It should not gain Harvester logic or become a new data feature
  entry point.
- Harvester must not import Deformation.

The audit command enforces Harvester import bans, direct Harvester data-path
bans, schema references, and backend config sanity:

```bash
python3 scripts/audit_research_os.py
```
