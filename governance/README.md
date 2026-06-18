# Governance Directory Index

This directory contains the system's policy registries, architecture decisions,
and audit evidence. **Start with [MODULES.md](../MODULES.md)** for the
project-wide routing table, then use this file to locate specific governance
documents.

---

## Reading Order

1. **[MODULES.md](../MODULES.md)** — project threads, status, owning paths
2. **[module_contexts/](../module_contexts/)** — per-module context files
3. **This directory** — policies, decisions, audit reports

---

## Constitution Layer (highest authority)

These files define hard rules that override all other documents.

| File | Purpose |
|------|---------|
| `system_constitution.yaml` | Core principles, module roles, authority ordering. Every module must obey these rules. |
| `architecture_reality_decisions.md` | Architectural decisions at constitution level. Overrides audit reports and module claims. Includes submodule transition plan (section 9). |
| `architecture_cleanup_decisions.md` | Cleanup principles (D1–D8). Physical move rules, retirement criteria, monorepo target structure. |

---

## Policy Registries (machine-checked or runtime-enforced)

| File | Purpose |
|------|---------|
| `daily_pipeline_registry.yaml` | Pipeline step I/O contracts — what each step reads/writes. |
| `entrypoint_registry.yaml` | Every script must be registered here with owner and allowed use. |
| `redundancy_budget.yaml` | Hard limits on script counts, artifact counts, data directories. |
| `module_authority_registry.yaml` | Per-module allowed/forbidden actions (ACQUIRE, PROMOTE, etc.). |
| `module_contract_registry.yaml` | Module contract definitions and boundaries. |
| `config_authority_registry.yaml` | Config ownership — who can change what settings. |
| `data_authority_registry.yaml` | Data ownership — who produces/consumes what data. |
| `data_request_registry.yaml` | Data request routing rules. |
| `data_retention_policy.yaml` | Retention rules for harvester exports, debug releases, experimental data. |
| `output_routing_policy.yaml` | Automatic routing, lifecycle, and archival of Output artifacts. |
| `governance_tiers.yaml` | Classifies all governance files into hard_rules / work_support / knowledge_background. |
| `operator_registry.yaml` | Operator definitions and capabilities. |
| `incentive_policy.yaml` | Priority incentive system — rewards compliant, useful contributions. |
| `authority_graph_policy.yaml` | Topology zones and bridge invariants; derived graph at `Output/system_learning/latest/authority_graph.json`. |
| `decay_policy.yaml` | Structural forgetting triggers and work_support budget. |
| `position_sizing_policy.yaml` | Position sizing rules. |
| `proxy_quality_rules.yaml` | Proxy quality scoring rules. |
| `canonical_proxy_spec.yaml` | Proxy quality specifications. |
| `opencode_supervisor_policy.yaml` | Supervisor policy for open-code sessions. |
| `run_mode_registry.yaml` | Run mode definitions (daily, replay, etc.). |
| `experimental_submission_registry.yaml` | Experimental submission tracking. |
| `pipeline_test_baseline.yaml` | Pipeline test baselines. |
| `deferred_work_register.yaml` | Work that cannot be completed short-term — maturity dates, review cadence, fallback plans. |

---

## Schema Files

| File | Purpose |
|------|---------|
| `capability_registry.schema.json` | JSON Schema for `capability_registry.yaml`. |
| `framework_output.schema.json` | JSON Schema for framework output format. |
| `semantic_registry.json` | Semantic distance registry. |

---

## Operational Registries

| File | Purpose |
|------|---------|
| `capability_registry.yaml` | Module status enum and capability matrix. Referenced by MODULES.md for status legend. |

---

## Markdown References

| File | Purpose |
|------|---------|
| `repo_layout_map.md` | Authoritative on-disk layout map. Defines physical directory structure. |
| `git_workspace_policy.md` | Git/submodule policy. Current layout is locked; retired options marked "do not reopen." |
| `submodule_commit_plan.md` | Submodule pin cleanup plan — dirty state inventory and commit slicing recommendations. |
| `run_observability_summary.template.md` | Template for run observability summaries. |

---

## Archive (`archive/`)

Retired policies that are no longer active but preserved for reference.
6 files. Do not use for current governance decisions.

---

## Audit Reports (`audit-reports/`)

34 one-time audit and migration reports. Classified as Layer 4 "Evidence" —
historical only, cannot override the constitution layer.

Key reports:
- `EXECUTION_REALITY_AUDIT_REPORT.md` — execution path audit
- `CAPABILITY_REALITY_MATRIX.md` — module capability ground truth
- `CANONICAL_RUNTIME_CONTRACT.md` — runtime contract specification
- `CALL_STACK_AUDIT.md` — call stack analysis
- `ZSCORE_MIGRATION_PLAN.md` — zscore migration plan and inventory

---

## Submodule Transition Status

The current 4-submodule structure is **transitional, not strategic**.

- **Buffer period:** 30–45 days from 2026-06-16 (target: mid-July to late July 2026)
- **Target:** Single-repo workspace with `packages/` directory
- **Tracking:** `architecture_reality_decisions.md` section 9, `submodule_commit_plan.md`
- **Detailed migration steps:** `repo_layout_map.md` section 7

Current submodules:
1. `Workbench/` → `packages/workbench/`
2. `Structural Deformation Research System/` → `packages/framework/`
3. `structural-risk-harvester/` → `packages/harvester/`
4. `system-learning-hub/` → `packages/learning_hub/`
