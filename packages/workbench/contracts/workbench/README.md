# Workbench Contracts

These contracts describe the neutral Product / Workbench layer. They are meant
to connect Data Providers, Frameworks, and user-facing tools without embedding
one layer inside another.

## Contracts

- `data_provider_release.schema.json`: a provider-published release bundle.
- `evidence_panel.schema.json`: public or private evidence exposed to tools.
- `model_run.schema.json`: a framework-produced run exposed to the Workbench.
- `openbb_secondary_audit.schema.json`: observe-only comparison of OpenBB
  probe data against Deformation outputs for Learning Hub ingestion.
- `report_artifact.schema.json`: a user-facing artifact that can be opened,
  indexed, or rendered.

## Human Templates

- `templates/data_provider_release.template.json`
- `templates/evidence_panel.template.csv`
- `templates/model_run.template.json`
- `templates/report_artifact.template.json`
- `templates/source_registry.template.json`
- `templates/provenance_record.template.jsonl`

## Examples

- `examples/minimal_provider_release/`
- `examples/minimal_framework_run/`

Validate examples from the workspace root:

```bash
python3 scripts/validate_workbench_contract.py provider-release contracts/workbench/examples/minimal_provider_release
python3 scripts/validate_workbench_contract.py model-run contracts/workbench/examples/minimal_framework_run/model_run.json
python3 scripts/validate_workbench_contract.py report-artifacts contracts/workbench/examples/minimal_framework_run/report_artifacts.json
```

Or:

```bash
./sys validate-contract provider-release contracts/workbench/examples/minimal_provider_release
./sys validate-contract model-run contracts/workbench/examples/minimal_framework_run/model_run.json
./sys validate-contract report-artifacts contracts/workbench/examples/minimal_framework_run/report_artifacts.json
```

## Boundary

The Workbench consumes protocol-shaped files. It should not import framework or
provider Python packages to understand their internals.

Framework-specific fields belong under `framework_payload`. Provider-specific
fields belong under `provider_payload`.

## Readable Standard

A payload is readable when:

1. `schema_version` exists and matches a known Workbench schema.
2. Required fields are present.
3. Artifact paths are relative to the release or run root.
4. Artifact `role` or `kind` is recognized by the consuming tool.
5. Data files have explicit columns or a known tabular schema.
6. Provenance identifies source, transformation, and checksum when available.

The Workbench should report unreadable inputs as `status: unreadable` with a
concrete reason. It should not guess missing semantics.
