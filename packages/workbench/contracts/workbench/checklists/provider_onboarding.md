# Provider Onboarding Checklist

Use this when a Data Provider wants to publish evidence for Workbench tools.

## Required Files

- `catalog.json` or `provider_release.json`
- `source_registry.json`
- `provenance.jsonl`
- `data/evidence_panel.csv` or `data/evidence_panel.parquet`

## Evidence Panel Columns

- `date`
- `series_id`
- `source_id`
- `source_series_id`
- `value`
- `unit`
- `frequency`
- `vintage_date`
- `quality_flag`

## Release Rules

- `schema_version` must be `workbench.data_provider_release.v1` when using the Workbench release contract.
- `status` must be `finalized` for normal Product consumption.
- Artifact paths must be relative to the provider release root.
- Each data artifact needs a stable `role`, such as `evidence_panel`.
- Each data artifact should include `format`, `sha256`, and `row_count` when available.
- Missing series should be represented by absence from the panel, not fabricated rows.
- Provider-specific details go under `provider_payload` or in `source_registry.json`.

## Validation

From the workspace root:

```bash
python3 scripts/validate_workbench_contract.py provider-release <release_dir>
python3 scripts/validate_workbench_contract.py evidence-panel <release_dir>/data/evidence_panel.csv
```

Readable means required fields exist, referenced paths exist, evidence columns
match, and status is not failed.
