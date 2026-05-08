# Folder Ownership

This file is the directory-level boundary map. Source code should not be
scattered across layers.

## Tool / Product Layer

Canonical source folder:

```text
Workbench/
```

Tool-owned subfolders:

```text
Workbench/src/workbench/                              # Product cockpit and surfaces
Workbench/src/workbench/workspace/                    # Workspace index/status/promotion tools
Workbench/contracts/workbench/                        # Protocol schemas/templates/examples
Workbench/data_providers/structural-risk-harvester/  # Data Provider tool
Workbench/agent_harness/structural-research-harness/ # Agent/API harness
Workbench/governance/system-learning-hub/             # Governance memory tool
```

Generated/user-facing output:

```text
Output/current/
Output/workbench/
```

Compatibility wrappers:

```text
./sys
scripts/refresh_output_current.py
scripts/build_benchmark_evidence_dashboard.py
scripts/build_artifact_navigator.py
scripts/validate_workbench_contract.py
scripts/build_system_index.py
scripts/list_latest.py
scripts/promote_snapshot.py
scripts/system_status.py
contracts -> Workbench/contracts
Structural Risk Harvester -> Workbench/data_providers/structural-risk-harvester
Structural Research Harness -> Workbench/agent_harness/structural-research-harness
System Learning Hub -> Workbench/governance/system-learning-hub
```

The wrappers must stay thin and delegate to `Workbench/src/workbench/`.

## Protocol Layer

Canonical folder:

```text
Workbench/contracts/workbench/
```

Protocol files are the only legal communication channel between Tool,
Framework, and Data Provider layers.

The top-level `contracts` path is a compatibility symlink, not the canonical
source location.

## Framework Core

Canonical source folder:

```text
Structural Deformation Research System/
```

Framework-owned subfolders include:

```text
src/proxies/
src/derivation/
src/operators/
src/diagnostics/
src/dynamics/
src/interpretation/
src/core/
src/claims/
wiki/
papers/
```

Framework code may produce Workbench protocol files. It must not own generic
Workbench product workflows.

## Data Provider

Canonical source folder:

```text
Workbench/data_providers/structural-risk-harvester/
```

Generated provider releases:

```text
Data/harvester/exports/
```

Data Providers publish releases and evidence. They do not encode Framework
theory.

The top-level `Structural Risk Harvester` path is a compatibility symlink, not
the canonical source location.

## Agent / API Harness

Canonical source folder:

```text
Workbench/agent_harness/structural-research-harness/
```

This owns agent-facing tools, hooks, policies, skills, and workflow guards. It
is Tool / Workbench code, not Framework code.

The top-level `Structural Research Harness` path is a compatibility symlink,
not the canonical source location.

## Governance Memory

Canonical source folder:

```text
Workbench/governance/system-learning-hub/
```

Generated governance output:

```text
Output/system_learning/
Data/system_learning/
```

The top-level `System Learning Hub` path is a compatibility symlink, not the
canonical source location.

## Workspace Index / Promotion Utilities

Compatibility wrapper folder:

```text
scripts/
```

These entries are compatibility wrappers:

```text
build_system_index.py
list_latest.py
promote_snapshot.py
system_status.py
```

Tool/Product source must not live here except as thin wrappers. Canonical
workspace utility source lives in `Workbench/src/workbench/workspace/`.

## Constitution-Level Red Line

Tool, Framework, and Data Provider layers must not directly understand each
other. They communicate only through Workbench contracts and protocol-shaped
artifacts.

Direct imports, hidden path coupling, semantic field peeking outside a contract,
or code that turns one layer into another layer's internal adapter are severe
boundary violations.

## Phase 2.5 Governance Closure

Timestamp: 2026-05-05T04:58:04Z

Owner: `research_os_layers`

Decision record:
`Output/system_learning/routing_decisions/2026-05-05-phase-2-5-canonicalization-closure.yaml`

The current LearningHub `architecture_drift` queue is classified for
canonicalization closure, not migrated in this pass.

`Structural Deformation Research System/src/data/adapters/public_adapters.py`
and `Structural Deformation Research System/src/data/gateway/` are temporary
legacy compatibility surfaces. They may remain in place for legacy replay,
old dashboard rendering, compatibility tests, and migration support. New
provider clients, API-key access, HTTP acquisition, or raw provider cache
logic must not be added there. New admitted evidence ownership remains with
Workbench/Harvester and Deformation should consume admitted releases through
`src/data_access/`.

`Structural Deformation Research System/src/data/data_sources.py` and
`Structural Deformation Research System/src/ui/components/paper_dashboard.py`
are accepted as oversized legacy surfaces for Phase 2.5 only. Splitting them
is explicitly deferred because it would start migration/refactor work. Future
Phase 3-5 work may decompose them under a separate routing decision.

`Structural Deformation Research System/tests/test_data_access_boundary.py`
is classified as detector noise/observe-only in the 2026-05-04 cartography
run because it is test code asserting the boundary, not production code
crossing it.
