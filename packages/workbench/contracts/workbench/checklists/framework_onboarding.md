# Framework Onboarding Checklist

Use this when a Framework wants to expose model outputs to the Workbench.

## Required Files

- `model_run.json`
- summary artifact, usually Markdown
- user-facing report artifact, usually HTML
- optional dashboard snapshot, JSON
- optional screenshot or static chart

## Model Run Rules

- `schema_version` must be `workbench.model_run.v1`.
- `model_id`, `run_id`, `status`, and `artifacts` are required.
- Artifact paths must be relative to the framework run root unless explicitly documented.
- Basic Workbench fields should be generic: run date, status, generated time, artifact paths.
- Framework-specific semantics must live under `framework_payload`.
- The Workbench may display `framework_payload`, but basic Product use must not require it.

## Validation

From the workspace root:

```bash
python3 scripts/validate_workbench_contract.py model-run <run_dir>/model_run.json
python3 scripts/validate_workbench_contract.py report-artifacts <run_dir>/report_artifacts.json
```

Readable means required fields exist, artifact paths have known `kind`, and
framework-owned interpretation is isolated inside `framework_payload`.
