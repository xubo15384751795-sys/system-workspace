# Current Architecture Dependency Map

- Generated at: 2026-09-12T04:06:25.883253+00:00
- Nodes: 1478; internal edges: 1716
- Gate: **PASS**

## Layer inventory

| Layer | Python modules |
|---|---:|
| application | 13 |
| application_runtime | 28 |
| archive | 284 |
| compatibility | 198 |
| core | 23 |
| domain | 369 |
| orchestration | 61 |
| tests | 422 |
| tools | 80 |

## Cross-layer edges

| Source | Target | Edges |
|---|---|---:|
| application | application_runtime | 14 |
| application | core | 22 |
| application | domain | 7 |
| application | orchestration | 8 |
| application_runtime | core | 16 |
| application_runtime | domain | 3 |
| application_runtime | orchestration | 9 |
| archive | application_runtime | 35 |
| archive | compatibility | 18 |
| archive | core | 9 |
| archive | domain | 12 |
| compatibility | application_runtime | 24 |
| compatibility | domain | 6 |
| domain | application_runtime | 95 |
| domain | core | 51 |
| domain | orchestration | 8 |
| orchestration | application | 2 |
| orchestration | application_runtime | 38 |
| orchestration | core | 34 |
| orchestration | domain | 20 |
| tests | application | 12 |
| tests | application_runtime | 61 |
| tests | compatibility | 37 |
| tests | core | 72 |
| tests | domain | 332 |
| tests | orchestration | 64 |
| tests | tools | 5 |
| tools | application_runtime | 26 |
| tools | core | 6 |
| tools | domain | 10 |
| tools | orchestration | 1 |

## Architecture violations

- Registered violations: 15
- Unregistered violations: 0
- All current violations have an owner: True

| Rule | Count |
|---|---:|
| ARCH-004 | 9 |
| ARCH-006 | 6 |

## Package to scripts

Production package to scripts edges: **0**

## Cycles

Detected strongly connected components: 3

| Category | Owner | Nodes |
|---|---|---:|
| error_ownership | Architecture migration | 2 |
| error_ownership | Architecture migration | 2 |
| error_ownership | Architecture migration | 2 |

## Focused ownership boundaries

| Boundary | Direct forward edges | Direct reverse edges | SCCs | Category | Owner |
|---|---:|---:|---:|---|---|
| verity ↔ orchestration | 16 | 40 | 0 | application_callback | Orchestration |
| verity ↔ workbench | 5 | 64 | 0 | shared_core_contract | System runtime |
| workbench ↔ orchestration | 7 | 19 | 0 | temporary_compatibility | Orchestration |

## Step 1 gate

| Check | Result |
|---|---|
| architecture_dag_written_to_test | True |
| all_existing_violations_have_owner | True |
| production_package_to_scripts_count | 0 |
| no_production_package_to_scripts | True |
| baseline_core_to_orchestration_domain_count | 0 |
| current_core_to_orchestration_domain_count | 0 |
| core_direction_not_increased | True |
| baseline_registered_violation_count | 22 |
| current_registered_violation_count | 15 |
| registered_debt_not_expanded | True |
| all_cycles_classified | True |
| focus_boundaries_classified | True |

This map is structural evidence. It does not promote provider, freshness, publication, or decision authority.
