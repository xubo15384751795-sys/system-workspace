# Workspace lineage

**Status:** historical record
**Authority:** this file explains names and layouts that no longer define the
product. Current identity is [Verity](../../README.md). Current paths are
[`governance/repo_layout_map.md`](../../governance/repo_layout_map.md).

This document keeps the former root README's archaeology so the homepage can
stay a product page.

## Historical names

The same checkout has been introduced as all of the following:

| Name | What it referred to | Current standing |
|---|---|---|
| Structural Risk Workbench | Root README title and product-shaped operator surface | Historical product name. Code still lives in `packages/workbench/`. |
| System Workspace | Operator-facing "research operating system" framing | Historical workspace name. The git repo is still `system-workspace`. |
| Deformation / Structural Deformation Framework | Host theory and framework runtime | Replaceable capability in `packages/framework/`. Do not treat it as the kernel. |
| Workbench | User-facing commands, dashboards, contracts | Implementation module, not the product name. |
| Verity | Evidence-governed research kernel | Current product identity (2026-08-19). |

Do not reintroduce these historical names as competing product titles in the
root README.

## Why the old homepage drifted

The former root README was an accurate maintainer note for an earlier phase:

```text
Workbench
Deformation
Learning Hub
System Index
Sandbox
```

That inventory described how the repository grew: compatibility symlinks, an
old submodule layout, Deformation downscope, and folder ownership. It did not
describe the chain the runtime now actually implements:

```text
Source → Observation → Measurement → Evidence → Claim → Judgment
       → Admission / Promotion / Publication
```

The former constitution also said "Data is the truth layer. Output is the
run/display layer." That rule correctly blocked Output from rewriting Data. It
is no longer sufficient: Current is published only through
`PublishAdmission` → `PublishTransaction` → `COMMITTED`. Durable data is not
runtime authority. See
[`docs/architecture/authority_runtime_matrix.md`](../architecture/authority_runtime_matrix.md).

## Historical pre-consolidation layout

Before the monorepo, the workspace was a root repo plus git submodules:

| Repo | Historical path | Current path |
|---|---|---|
| `system-workspace` | `/` | `/` |
| `structural-workbench` | `Workbench/` | `packages/workbench/` |
| `Structural-Deformation-Research-System` | `deformation-framework/` | `packages/framework/` |
| `structural-risk-harvester` | `structural-risk-harvester/` | `packages/harvester/` |
| `system-learning-hub` | `system-learning-hub/` | `packages/learning_hub/` |

There is no `.gitmodules` file now. `scripts/bootstrap.sh` verifies
`packages/` and recreates compatibility aliases only. Do not clone with
`--recurse-submodules`.

Active compatibility aliases:

| Alias | Target |
|---|---|
| `Structural Risk Harvester` | `packages/harvester/` |
| `System Learning Hub` | `packages/learning_hub/` |
| `Structural Research Harness` | `packages/workbench/agents/harness/` |
| `contracts` | `packages/workbench/contracts/` |

Folder-level ownership of the live tree remains in
[`FOLDER_OWNERSHIP.md`](../../FOLDER_OWNERSHIP.md). The layout map is
authoritative when those docs disagree.

## Historical main flow

The former README described this promotion path:

```text
external providers
  -> Workbench Data Provider / Harvester acquisition / provenance
  -> Data/harvester/exports/<release_id>/
  -> Deformation src/data_access/
  -> Deformation runtime, diagnostics, UI, reports
  -> Output/deformation_runs/<run_id>/
  -> scripts/promote_snapshot.py
  -> Data/deformation/snapshots/<snapshot_id>.json
```

`promote_snapshot.py` still exists as a Deformation snapshot promotion tool.
It is not the Current-pointer authority. Current publication is:

```text
Candidate Generation
  -> PublishAdmission
  -> PublishTransaction
  -> COMMITTED
  -> Output/current
```

## Deformation downscope

Deformation should not continue growing as a data acquisition system.

Keep in the framework package:

- `src/core`, `src/derivation`, `src/dynamics`, `src/operators`
- `src/proxies`, `src/diagnostics`, `src/validation`
- framework-specific benchmark evaluation
- case replay and scenario labs
- framework-specific runtime and interpretation surfaces
- wiki, paper, and claim governance
- thin `src/data/gateway/` shim over `src/data_access/`

Move or freeze out of the framework package:

- provider-specific downloaders
- raw/processed data ownership
- corpus acquisition providers
- dataset source documentation
- acquisition or source-validation notebooks
- data-agent prompts
- source registry publication
- Harvester bundle creation
- generated benchmark report artifacts
- generic UI/API/report rendering and artifact navigation
- generic benchmark evidence dashboards

## Historical note ownership

- Source, dataset, acquisition, and data-quality notes live in Harvester /
  Workbench data-provider surfaces.
- Structural interpretation, cases, mechanisms, variables, methods, and
  claims live in the framework package.
- Generated artifacts live in `Output/`.
- Canonical (post-promotion) artifacts live in `Data/`.
- Cross-system routing rules live in `ROUTING_CONSTITUTION.md`.

## Sparse activation routing

Default posture: smallest sufficient expert set first. Add experts when a
task crosses layer boundaries, touches protected artifacts, triggers coupling
rules, or prepares an output for release.

- `ROUTING_CONSTITUTION.md`: global deny rules, layer authority, activation
  discipline.
- Concrete records live under `governance/routing_decisions/` and
  `Output/system_learning/routing_decisions/`.

## Outstanding workspace gaps (as of 2026-05-03)

These were recorded in `Output/system_learning/events/events_2026-05-03.jsonl`
and surfaced by `scripts/system_status.py`. They remain historical operator
notes, not the current stabilization close-out.

| Gap | Owner | Action |
|---|---|---|
| `operator_trace.jsonl` missing in `2026-04-22_WEEKLY` | deformation-framework | Runner must emit one JSON object per applied operator. |
| `config_snapshot.json` was backfilled, not captured at run time | deformation-framework | Runner must serialise resolved config before completing. |
| `latest` symlink misuse risk | Workspace / agents | Always inspect via `find -L` / `realpath`. |

Current remaining closure work is SYS-15, SYS-7, and SYS-19 on the scheduled
path. See the root README project-status section and
[`docs/architecture/authority_runtime_matrix.md`](../architecture/authority_runtime_matrix.md).
