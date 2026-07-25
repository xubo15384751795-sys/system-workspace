# Harvester Access Protocol

**Status**: FROZEN
**Schema family version**: 1.0
**Last modified**: see commit history; once frozen, content changes require version bump.

## 0. Purpose

This document defines how data flows from the Harvester system to consumers
(notably the Deformation system). It establishes:

- The on-disk layout of Harvester output.
- The contract that consumers rely on.
- The immutability and versioning rules that make Harvester output
  reproducible and audit-safe.

This protocol is the **only** sanctioned channel between Harvester and any
consumer. Reading raw provider files, working directories, or undocumented
paths is a protocol violation.

## 1. Boundary statement

Harvester is responsible for:

- Acquiring data from external sources.
- Recording provenance (who, when, from where, by what means).
- Producing immutable, manifest-backed bundles.
- Enforcing per-release immutability after finalization.

Harvester is **not** responsible for:

- Interpreting data.
- Deriving theoretical constructs.
- Maintaining consumer-side caches or state.
- Backfilling or rewriting historical bundles after they are finalized
  (revisions are published as new releases, not as edits to old ones).

Consumers are responsible for:

- Discovering datasets via `catalog.json`.
- Loading data **only** through paths declared in manifests.
- Verifying `sha256` of every loaded data file against the manifest.
- Pinning to specific `release_id` values for reproducible work.

Consumers are **not** permitted to:

- Read files under `data/raw/`, `data/processed/`, `data/corpus/`, or any
  path not declared in a manifest.
- Modify any file under any finalized release directory.
- Treat `latest` as a stable identifier for paper-grade work.

## 2. On-disk layout

The Harvester repository is rooted at the directory containing this file's
parent (`contracts/`'s parent is the repo root).

The data volume is reached via the `data/` symlink at the repo root, which
points to a non-versioned storage location.

```
<repo_root>/
├── contracts/                     ← this directory; in git
├── src/harvester/                 ← code; in git
├── tests/                         ← code; in git
├── docs/                          ← code; in git
└── data/                          ← symlink to data volume; symlink target NOT in git
        ├── exports/               ← protocol surface; immutable releases
        │   ├── latest -> 2026-04-26-r1     ← mutable pointer; see §5
        │   ├── 2026-04-26-r1/              ← immutable release
        │   │   ├── catalog.json
        │   │   ├── release_digest.txt
        │   │   ├── manifests/
        │   │   │   ├── <dataset_id>.manifest.json
        │   │   │   └── ...
        │   │   ├── provenance/
        │   │   │   ├── <dataset_id>.provenance.json
        │   │   │   └── ...
        │   │   ├── quality_reports/
        │   │   │   ├── <dataset_id>.quality.json
        │   │   │   └── ...
        │   │   └── data/
        │   │       ├── <dataset_id>.<ext>
        │   │       └── ...
        │   └── 2026-04-27-r1/
        ├── manifests/             ← provider-internal manifest staging; out of scope
        ├── provenance/            ← provider-internal provenance staging; out of scope
        ├── quality_reports/       ← provider-internal quality staging; out of scope
        ├── raw/                   ← provider-internal; out of scope
        ├── processed/             ← provider-internal; out of scope
        └── corpus/                ← provider-internal; out of scope
```

## 3. Scope

**In-scope (protocol-governed, consumer-visible):**

- `data/exports/<release_id>/catalog.json`
- `data/exports/<release_id>/release_digest.txt`
- `data/exports/<release_id>/manifests/<dataset_id>.manifest.json`
- `data/exports/<release_id>/provenance/<dataset_id>.provenance.json`
- `data/exports/<release_id>/quality_reports/<dataset_id>.quality.json`
- `data/exports/<release_id>/data/<dataset_id>.<ext>`

**Out-of-scope (provider-internal, NOT consumer-visible):**

- `data/raw/`
- `data/processed/`
- `data/corpus/`
- `data/manifests/` (note: this is the provider staging area; the
  authoritative consumer-visible manifests live under
  `data/exports/<release_id>/manifests/`)
- `data/provenance/`
- `data/quality_reports/`

Provenance files MAY reference out-of-scope paths via the
`internal_reference` field for audit purposes. Consumers MUST NOT follow
these references at load time.

## 4. Release identifiers

A release is identified by `release_id` of the form:

```
YYYY-MM-DD-rN
```

where:

- `YYYY-MM-DD` is the UTC date of finalization.
- `r` is a literal lowercase letter.
- `N` is a positive integer starting at 1, monotonically increasing within
  a single calendar day.

Examples: `2026-04-26-r1`, `2026-04-26-r2`, `2026-04-27-r1`.

`release_id` is part of the directory name and MUST match the `release_id`
field inside `catalog.json`.

## 5. Immutability rules

### 5.1 Bundle immutability (strict)

Once a release directory `data/exports/<release_id>/` is finalized:

- No file under that directory MAY be modified, deleted, renamed, or
  replaced.
- No file MAY be added to that directory.
- Finalization is recorded by the presence of a non-empty
  `release_digest.txt` at the release root.
- Implementations SHOULD set the directory and its contents to read-only
  permissions after finalization. Implementations MUST refuse to finalize
  twice.

If a published release is later found to contain errors, the correct
remedy is to publish a new release (e.g., `2026-04-27-r1`) that supersedes
it. The erroneous release remains untouched.

### 5.2 Pointer mutability (narrow exception)

The symlink `data/exports/latest` MAY change to point to any finalized
release. The symlink itself is not part of any release's immutable bundle.

**Consumer rule**: paper-grade and reproducible work MUST pin to a specific
`release_id`. Use of `latest` is restricted to exploratory work and MUST be
recorded in the consumer's own provenance.

## 6. Time semantics

Two time concepts are first-class:

- `as_of_date`: the time the data **describes** (the world state).
- `vintage_date`: the time the data was **observed/published/recorded**
  (the act of measurement).

These are independent. The same `as_of_date` may have multiple
`vintage_date` values across releases, reflecting upstream revisions.

**No-lookahead requirement**: when a consumer is simulating a decision at
wall-clock time `T`, it MUST filter to data where `vintage_date <= T`. It
is incorrect to filter only on `as_of_date <= T`.

**Derived datasets**: if dataset B is derived from dataset A, B's
`as_of_date` SHOULD be inherited from A (same world state being described).
B's `vintage_date` is the time of derivation, not A's vintage.

## 7. Schema versioning

Each schema (`catalog`, `dataset_manifest`, `provenance`, `quality_report`)
declares a `schema_version` of the form `MAJOR.MINOR`.

- **MINOR increment** (backwards compatible): adds optional fields, extends
  enumerations with new values, relaxes constraints. Consumers built for
  `MAJOR.K` must continue to work with `MAJOR.K+m` for any `m >= 0`.
- **MAJOR increment** (breaking): removes fields, renames fields, changes
  field semantics, changes a field from optional to required (or vice
  versa), tightens constraints in a way that previously valid data becomes
  invalid.

Consumers MUST declare the MAJOR versions they support. A consumer
encountering a higher MAJOR version MUST refuse to load and report a clear
error.

The current schema family version is **1.0**. All schemas in this Phase 2
freeze are version `1.0`.

## 8. Integrity verification

Two layers of integrity protection:

### 8.1 Per-file digest (mandatory at load time)

Every data file's `sha256` is recorded in its manifest's `data_file.sha256`
field. Consumers MUST recompute the sha256 of every loaded data file and
reject any mismatch with a hard error (no silent fallback, no warning-only
mode).

### 8.2 Release digest (release-level integrity)

`release_digest.txt` contains a single line:

```
sha256:<hex>
```

where `<hex>` is the sha256 of `catalog.json`'s bytes. This allows external
recording (e.g., in a paper appendix) of "the catalog I used was X" without
storing the full catalog.

Consumers SHOULD verify `release_digest.txt` against `catalog.json` at load
time when loading any dataset for paper-grade work.

## 9. Failure modes

Consumers MUST treat the following conditions as hard errors and refuse to
proceed:

- `catalog.json` missing, unparseable, or failing schema validation.
- `release_digest.txt` missing or not matching `catalog.json`'s sha256
  (when verification is requested).
- Manifest referenced in catalog is missing, unparseable, or failing
  schema validation.
- Provenance file referenced in manifest is missing, unparseable, or
  failing schema validation.
- Data file referenced in manifest is missing or has sha256 mismatch.
- Manifest's `schema_version` MAJOR is higher than the consumer supports.
- Release directory lacks `release_digest.txt` (i.e., not finalized).

Consumers MUST NOT silently fall back to a previous release, to `latest`,
to legacy data sources, or to default values. Any "graceful degradation"
defeats the purpose of this protocol.

## 10. Out-of-scope concerns

This protocol does NOT specify:

- How the Harvester acquires data from external sources.
- How providers internally organize their work (under `raw/`, `processed/`,
  `corpus/`).
- Streaming or push-based delivery (Harvester is pull/poll only).
- Access control or authentication (handled at filesystem layer).
- Real-time guarantees (Harvester is batch-oriented).

These may be specified in future protocol versions or in separate
documents.

## 11. References

- Schema files (this directory):
  - `catalog.schema.json`
  - `dataset_manifest.schema.json`
  - `provenance.schema.json`
- Future: `quality_report.schema.json` (out of scope for Phase 2).

## 12. Notes on 1.0 boundaries

This section clarifies the intended scope of schema family 1.0. It is
explanatory, not normative — it does not introduce new constraints, but
makes existing ones explicit and forecloses ambiguous interpretations
that have been raised during review.

### 12.1 Vintage granularity is dataset-level in 1.0

The `vintage_date` field on a dataset manifest applies to the dataset as
a whole. Schema 1.0 does **not** support row-level vintage (i.e., a
single data file containing multiple observations of the same underlying
series at different vintage dates).

Implications for providers:

- Datasets that undergo upstream revisions (e.g., NFCI, OFR FSI, FRED
  series subject to retroactive correction) MUST be published as a new
  release each time a revision is incorporated. The previous release's
  `vintage_date` remains accurate for the bytes it contains.
- Providers MUST NOT silently overwrite a prior release with revised
  values; doing so violates §5.1 (bundle immutability).

Implications for consumers:

- For point-in-time queries against a revising series, consumers MUST
  iterate across releases and select the manifest whose `vintage_date`
  is the latest value `<= T` (the simulated wall-clock time).
- Consumers MUST NOT assume the data file contains a vintage column.
  Column-level vintage is not part of 1.0.

Row-level vintage is a planned extension for schema family **1.1**. It
will not be added as an optional field within 1.0, in order to avoid
silently bifurcating the protocol surface.

### 12.2 Cross-system derivation: identity is a provider responsibility

When a dataset's `source.kind == "derived"` and the derivation is
performed by a system **outside Harvester** (e.g., the Deformation system
producing a proxy and depositing it back into Harvester), the
`derivation.upstream` field captures Harvester-side dependencies but
cannot capture the external system's identity (its code commit, its
configuration, its own internal upstream).

In such cases, the provider MUST record the external system's identity
inside the provenance file:

- `provenance.transformations[].code_reference` SHOULD identify the
  external system and its commit, e.g.
  `"deformation@<git_sha>:src/proxies/anchor_drift.py"`.
- `provenance.transformations[].params` SHOULD include any configuration
  or hyperparameter hashes needed to reproduce the derivation.

This responsibility is on the provider, not on the schema. Schema 1.0
deliberately does not introduce a dedicated `external_system` field,
because the existing free-form `params` and `code_reference` are
sufficient and the use case is rare in 1.0.

### 12.3 The `transformations` array records history, not just success

The `transformations` array in a provenance file records **all** steps
that were attempted, including those with `outcome` of `failed` or
`skipped`. It is an append-only audit log, not a recipe for reproducing
the final output.

Consumers and tooling MUST treat `checksums.final_sha256` as the
authoritative final hash. Implementations MUST NOT derive the final hash
from `transformations[-1].output_sha256` or any other element of the
transformations array, because the final element may have
`outcome != "success"` and the success path may not be the trailing
contiguous segment.

### 12.4 Empty-dataset releases are permitted but constrained

Schema 1.0 permits a catalog with an empty `datasets` array (see
`catalog.schema.json`, `datasets.minItems: 0`). This accommodates
"protocol-only" releases — for example, releases that exist solely to
record a Harvester tooling upgrade without data churn.

When a release has zero datasets, the catalog's `notes` field MUST
contain a non-empty explanation of why the release exists. This
constraint is enforced at the documentation and audit layer, not by the
JSON schema, because conditionally requiring a field is awkward to
express in JSON Schema and would obscure the catalog's structural
contract.

A release audit (see future `scripts/audit_research_os.py` rule) MUST
flag any empty-dataset release whose `notes` field is empty or missing.
Until that audit rule is in place, providers MUST self-enforce this
constraint.

### 12.5 What §12 does and does not do

§12 is a clarification of 1.0's scope. It does not modify any schema
file, does not introduce new required fields, and does not trigger a
schema version bump. Its purpose is to prevent silent disagreement
during Phase 3+ implementation by making four boundary decisions
explicit.

Future schema versions (1.1, 2.0) MAY render parts of §12 obsolete.
When that happens, the obsolete subsections will be marked as such with
a forward reference, not deleted.
