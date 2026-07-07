# Harvester Architecture

Harvester is a peer data system. Its job is to acquire bytes, describe them,
verify them, and publish them as immutable artifact bundles. It does not
interpret the data and it does not call into Deformation.

## Three Layers

### 1. Discovery

Discovery belongs to providers. A provider knows how to find or acquire a
source: an API endpoint, public file, manually curated corpus item, subscription
export, or derived upstream artifact.

Discovery output is not consumer-visible by itself. Raw files, working caches,
intermediate tables, and corpus staging live under provider-internal storage
such as `data/raw/`, `data/processed/`, or `data/corpus/`. These paths are not
part of the access protocol.

### 2. Manifest

The manifest layer turns provider output into a contract-backed dataset. Each
dataset has:

- a dataset manifest validated by `contracts/dataset_manifest.schema.json`
- a provenance record validated by `contracts/provenance.schema.json`
- a data file with declared format, byte size, row count when applicable, and
  sha256
- explicit `as_of_date` and `vintage_date`

The manifest layer is where no-lookahead discipline becomes enforceable.
`as_of_date` describes the world state covered by the dataset; `vintage_date`
describes when that observation was collected or published.

### 3. Access

The access layer is the finalized export bundle:

```text
data/exports/
├── latest -> 2026-04-26-r1/
└── 2026-04-26-r1/
    ├── catalog.json
    ├── release_digest.txt
    ├── .finalized
    ├── manifests/<dataset_id>.manifest.json
    ├── provenance/<dataset_id>.provenance.json
    └── data/<dataset_id>.<ext>
```

Consumers start at `catalog.json`, select a dataset entry, read the manifest,
validate the schema, verify the data hash, and only then load the data file.
Consumers do not read raw provider directories.

## Finalization

`harvester.core.exporter.finalize_release()` is the publication gate. It is dry
run by default. A real finalization requires `dry_run=False` or CLI
`--no-dry-run`.

Finalization checks:

- release directory exists
- required subdirectories exist
- every manifest validates against the frozen schema
- every declared data file exists
- byte size and sha256 match the manifest
- provenance exists and agrees with the manifest
- optional quality reports exist when declared

On success it writes `catalog.json`, `release_digest.txt`, `.finalized`,
updates `latest`, and marks the release read-only.

## Peer Boundary

Harvester and Deformation communicate by immutable files plus JSON contracts.
There is no service call and no Python import edge between the systems.
Deformation consumes Harvester output through its own `src/data_access/`
adapter, using Harvester's schema files by path.
