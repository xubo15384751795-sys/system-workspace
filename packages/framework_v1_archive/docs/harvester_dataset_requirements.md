# Harvester Dataset Requirements

This document is Deformation's request sheet for Risk Harvester. Harvester owns
provider code, acquisition timing, publication, lineage, provenance, schemas,
and hashes. Deformation consumes finalized, manifest-backed artifacts through
`src/data_access/` and maps them into research semantics.

Default runtime remains:

```yaml
data_backend: legacy
harvester:
  root: ../Structural Risk Harvester
  require_finalized: true
```

Switching to `data_backend: harvester` must fail fast if the catalog is missing,
a release is not finalized, a schema does not validate, a hash does not match,
or a required dataset contract below is unavailable.

## Access Rule

All Harvester-backed data enters through:

```text
src/data_access/harvester_adapter.py
```

The required read sequence is:

```text
catalog.json -> manifest -> provenance/schema/hash check -> data file
```

No proxy, benchmark, diagnostic, replay, report, UI, API, or script module
should read Harvester `raw/`, `processed/`, `corpus/`, or `exports/*/data/`
paths directly.

## Required Datasets

| dataset_id | Purpose | Required columns | Date column | Frequency | Point-in-time | Minimum history | Consumers |
|---|---|---|---|---|---|---|---|
| `benchmark_panel` | Public stress and baseline comparison panel. | `date`, `series_id`, `value`, `source_role`, `frequency` | `date` | daily or declared source frequency | yes | 10 years when available | `src/benchmarks/`, `src/reports/`, `src/ui/pages/9_public_benchmark.py` |
| `proxy_candidate_panel` | Candidate inputs for `M/D/K/X` proxy construction. | `date`, `signal_id`, `value`, `source_role`, `frequency`, `channel_hint` | `date` | daily preferred; weekly/monthly allowed with policy | yes | 5 years when available | `src/proxies/`, `src/derivation/proxy_builder.py`, `src/research/candidate_signal_factory.py` |
| `event_log` | Dated event evidence for replay and operator sequencing. | `event_id`, `event_date`, `event_type`, `title`, `source_role`, `description` | `event_date` | event-time | yes | case dependent | `src/operators/`, `src/benchmarks/historical_replay.py`, `src/simulation/`, `src/ui/pages/3_case_replay.py` |
| `corpus_index` | Manifest-backed index of research corpus artifacts. | `document_id`, `publication_date`, `institution`, `title`, `source_role`, `artifact_uri`, `license_status` | `publication_date` | document-time | yes | case dependent | `src/research_corpus/`, `src/observability/`, `wiki/`, reports |
| `structural_state_inputs` | Primitive-state inputs for `S/A/L/V/P/tau` and derived structural state. | `date`, `signal_id`, `value`, `primitive_hint`, `source_role`, `frequency` | `date` | daily/weekly/monthly with policy | yes | 5 years when available | `src/derivation/`, `src/diagnostics/`, `src/dynamics/`, `src/ui/pages/1_current_state.py` |
| `public_baseline_series` | Single-series public baselines for validation and paper-facing comparisons. | `date`, `series_id`, `value`, `source_role`, `frequency` | `date` | source frequency | yes | 10 years when available | `src/validation/`, `src/benchmarks/public_baselines.py`, `reports/` |

## Semantic Mapping Layer

Harvester dataset IDs and column names do not need to match Deformation's
internal names exactly. Deformation should maintain mapping behind
`src/data_access/` for:

- Harvester `dataset_id` to Deformation table or signal family.
- Harvester column names to expected internal column names.
- Source frequency to Deformation resampling policy.
- `source_role` to benchmark, proxy candidate, corpus, event, or legacy usage.

Research modules should request semantic datasets from `src/data_access/` and
avoid per-module column guessing.

## Startup Readiness

When `data_backend: harvester`, startup readiness should verify:

- Required `dataset_id` values exist in the active catalog.
- Each manifest validates against Harvester contracts.
- Required columns are present.
- Date column and declared frequency are usable.
- Minimum coverage is satisfied or explicitly waived by config.
- `source_role` values keep benchmark, proxy, corpus, event, and derived data
  separate.

Failure should stop startup. It should not silently fall back to legacy.

## Migration Checks

During migration, Deformation should compare legacy and Harvester-backed loads
for selected datasets:

- row count
- date coverage
- key column coverage
- basic summary statistics
- source role distribution

Differences are allowed when explained, but they should be recorded instead of
appearing halfway through a research run.

## Derived Outputs

If Deformation publishes derived datasets back for Harvester to archive, the
artifact provenance should record:

- `produced_by: Deformation`
- Deformation commit, config, and run ID
- upstream Harvester release ID
- input dataset IDs and revisions

Harvester should archive those derived artifacts without importing Deformation
code to compute them.
