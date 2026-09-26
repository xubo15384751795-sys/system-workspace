# Data and Output Context

Data is the canonical truth layer. Output is the run and display layer. They are
related, but they are not interchangeable.

## Owns

- canonical data state
- promoted snapshots
- harvester releases
- system index
- run artifacts
- current/latest pointers
- artifact state transitions
- promotion boundaries

## Primary Paths

- `Data/`
- `Data/harvester/exports/`
- `Data/deformation/snapshots/`
- `Data/system_index/`
- `Data/system_learning/`
- `Output/`
- `Output/current/`
- `Output/deformation_runs/`
- `Output/workbench/`
- `Output/system_learning/`
- `Output/state/sandbox/`
- `scripts/list_latest.py`
- `scripts/promote_snapshot.py`
- `scripts/build_system_index.py`
- `packages/orchestration/orchestration/dvc_promote.py` (DVC pointer sidecars)
- `Data/.dvc_cache/` (local DVC remote; gitignored)

## Reads

- Harvester release manifests
- Deformation run manifests
- protocol-shaped output files
- promotion records
- latest symlinks, resolved with symlink-aware commands

## Writes

- canonical promoted artifacts under `Data/`
- generated run/display artifacts under `Output/`
- system index files
- promotion outputs and summary records

## Promises

- `Data/` changes only through an explicit promotion path; `Output/` remains non-canonical.
- `Output/state/sandbox/` is a lawful zero-justification variation zone with zero authority.
- No sandbox artifact reaches current merely because its file exists or looks fresh.

## Relies On

- Producers promise manifests, lineage and stable run identity.
- Admission and publication gates promise zero authoritative side effects on rejection.

## Must Not

- treat Output as canonical truth without promotion
- treat `latest` symlinks as ordinary empty folders
- copy large report artifacts into `Output/current/` when a pointer is enough
- let sandbox probes feed Framework directly
- mutate released canonical data casually

## Read First

- `MODULES.md`
- this file
- `README.md`
- `FOLDER_OWNERSHIP.md`
- `scripts/list_latest.py`
- `scripts/promote_snapshot.py`
- relevant protocol schema files

## Escalate When

- a run-local artifact should become canonical
- a latest pointer is broken or ambiguous
- Data and Output disagree
- sandbox output is proposed as production evidence
- promotion changes a protocol or manifest shape

Escalation usually goes to `protocols.md`, `harvester.md`, `framework.md`, or
`learning-hub.md`.

## Governed Promotion

Snapshot promotion must go through the Harness ToolSpec gate:

```text
system tools run artifact.promote_snapshot_preflight run_id=<RUN_ID> --mode verify --json
system tools run artifact.promote_snapshot run_id=<RUN_ID> --mode release --json
```

The preflight is read-only and reports blockers/provenance limits. The actual
promotion is a `snapshot_publish` action and requires manual review in release
mode; do not bypass it with the bare `scripts/promote_snapshot.py` path.
