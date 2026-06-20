# Entry Point Inventory

Generated: 2026-06-03
Scope: All executable entry points in `/Users/a1/System`

## Summary

| Type | Count | Active | Orphaned |
|------|-------|--------|----------|
| CLI (`./sys` commands) | 13 | 13 | 0 |
| Scripts (`if __name__`) | ~50 | ~35 | ~15 |
| Agent Harness Entrypoints | 4 | 3 | 1 |
| Harvester CLI | 1 | 1 | 0 |
| **Total** | **~68** | **~52** | **~16** |

---

## 1. CLI — `./sys` Commands (13)

All routed through `/Users/a1/System/sys` (bash).

| Command | Downstream Script | Status |
|---------|-------------------|--------|
| `./sys check` / `./sys current` | `Output/current/00_READ_ME_FIRST.md` (direct read) | ACTIVE |
| `./sys refresh` | `scripts/refresh_output_current.py` → `scripts/build_artifact_navigator.py` | ACTIVE |
| `./sys open` | Opens `Output/current/00_READ_ME_FIRST.md` + `latest_report.html` | ACTIVE |
| `./sys next` / `./sys learning` | `Output/current/next_actions.md` (direct read) | ACTIVE |
| `./sys evidence` | `scripts/build_benchmark_evidence_dashboard.py` | ACTIVE |
| `./sys explain` | `Output/current/00_READ_ME_FIRST.md` (grep Framework Diagnosis) | ACTIVE |
| `./sys ask` | `scripts/ask_evidence.py` | ACTIVE |
| `./sys artifacts` | `scripts/build_artifact_navigator.py` | ACTIVE |
| `./sys validate-contract` | `scripts/validate_workbench_contract.py` | ACTIVE |
| `./sys report` | Opens `Output/current/latest_report.html` | ACTIVE |
| `./sys doctor` | Validates `Output/current` symlinks | ACTIVE |
| `./sys status` | `scripts/system_status.py` | ACTIVE |
| `./sys framework` | `scripts/framework_cli.py` | ACTIVE |

---

## 2. Scripts with `if __name__ == "__main__"` (~50)

### deformation-framework

| Script | Status | Notes |
|--------|--------|-------|
| `scripts/fetch_full_benchmark_panel.py` | ACTIVE | Fetches harvester data for benchmark panel |
| `scripts/dual_path_compare.py` | ACTIVE | Compares Deformation vs Workbench paths |
| `scripts/run_information_tests.py` | ACTIVE | Runs information-theoretic tests |
| `scripts/backfill_runtime_snapshots.py` | ACTIVE | Backfills snapshot store |
| `scripts/render_latest_result.py` | ACTIVE | Renders latest Deformation output |

### Scripts/ Directory

| Script | Status | Notes |
|--------|--------|-------|
| `scripts/bridge_replay_to_current.py` | ACTIVE | Bridges structural replay → `framework_output.json` |
| `scripts/structural_replay_v2.py` | ACTIVE | 4-channel structural replay, 16 events |
| `scripts/refresh_output_current.py` | PARTIAL | Links to stale Deformation run, bypassed by bridge |
| `scripts/archive/compute_proxies.py` | ARCHIVED | Was: Computes proxy series (moved to archive) |
| `scripts/merge_data_hub.py` | ACTIVE | Merges data hub sources |
| `scripts/run_harvester_no_proxy.py` | ACTIVE | Runs harvester without proxy computation |
| `scripts/system_status.py` | ACTIVE | Workspace subsystem status |
| `scripts/framework_cli.py` | ACTIVE | Framework registration CLI |
| `scripts/build_artifact_navigator.py` | ACTIVE | Builds artifact navigator markdown |
| `scripts/build_benchmark_evidence_dashboard.py` | ACTIVE | Evidence dashboard builder |
| `scripts/build_system_index.py` | ACTIVE | System index builder |
| `scripts/record_runtime_event.py` | ACTIVE | Records runtime events to learning hub |
| `scripts/ask_evidence.py` | ACTIVE | Grounded Q&A over evidence |
| `scripts/audit_boundaries.py` | ACTIVE | Boundary audit script |
| `scripts/wiki_system_bridge_audit.py` | ACTIVE | Wiki system bridge audit |
| `scripts/prepare_dl_training_data.py` | ACTIVE | DL training data preparation |
| `scripts/nlp_extract.py` | ACTIVE | NLP extraction |
| `scripts/nlp_ingest.py` | ACTIVE | NLP ingestion |
| `scripts/build_c005_morphology_report.py` | ACTIVE | C005 morphology report builder |
| `scripts/run_c005_morphology_replay.py` | ACTIVE | C005 morphology replay runner |
| `scripts/structural_replay_evaluation.py` | ACTIVE | Structural replay evaluation |
| `scripts/openbb_secondary_audit.py` | ACTIVE | OpenBB secondary audit |
| `scripts/repair_openbb_entrypoints.py` | ACTIVE | OpenBB entrypoint repair |
| `scripts/promote_snapshot.py` | ACTIVE | Snapshot promotion |
| `scripts/github_preflight.py` | ACTIVE | GitHub preflight checks |
| `scripts/build_system_index.py` | ACTIVE | System index builder |
| `scripts/_check_data.py` | ACTIVE | Data checking utility |
| `scripts/_count_project.py` | ORPHANED | Project counting utility, one-off |
| `scripts/_run_descriptive_quality_tests.py` | ACTIVE | Descriptive quality tests |
| `scripts/_test_fred_provider.py` | ORPHANED | One-off FRED provider test |

### Visualization

| Script | Status | Notes |
|--------|--------|-------|
| `Visualization/generate_report.py` | ACTIVE | Generates HTML report |

### Research Terminal

| Script | Status | Notes |
|--------|--------|-------|
| `research_terminal/cli.py` | ACTIVE | Research terminal CLI entry point |
| `research_terminal/report.py` | ACTIVE | Report generator |

### Paper-Empirical-Interface

| Script | Status | Notes |
|--------|--------|-------|
| `paper-empirical-interface/src/paper_interface/main.py` | ACTIVE | Paper interface main entry |

### External Tools

| Script | Status | Notes |
|--------|--------|-------|
| `ExternalTools/qlib_benchmark_runner/run_qlib_benchmark.py` | ACTIVE | Qlib benchmark runner |

### Top-Level Scripts

| Script | Status | Notes |
|--------|--------|-------|
| `check_candidates.py` | ORPHANED | One-off candidate check |
| `check_panel.py` | ORPHANED | One-off panel check |

---

## 3. Agent Harness Entrypoints (4)

All under `/Users/a1/System/Workbench/agents/harness/entrypoints/`.

| File | Class/Function | Status | Notes |
|------|---------------|--------|-------|
| `system.py` | SystemEntrypoint | ACTIVE | Main system entrypoint |
| `harvester_cli.py` | HarvesterCLI | ACTIVE | Harvester CLI integration |
| `deformation_cli.py` | DeformationCLI | ACTIVE | Deformation run CLI |
| `learning_hub_cli.py` | LearningHubCLI | ACTIVE | Learning hub CLI |

---

## 4. Harvester CLI (1)

| File | Entry | Status |
|------|-------|--------|
| `structural-risk-harvester/src/harvester/cli.py` | `harvester.cli` | ACTIVE |
| `structural-risk-harvester/src/harvester/__main__.py` | `python -m harvester` | ACTIVE |

---

## 5. Learning Hub Entrypoints

| File | Entry | Status |
|------|-------|--------|
| `system-learning-hub/src/system_learning/__main__.py` | `python -m system_learning` | ACTIVE |
| `system-learning-hub/src/system_learning/cli.py` | `learning-hub` CLI | ACTIVE |
| `system-learning-hub/src/system_learning/cartography/__main__.py` | Cartography runner | ACTIVE |
| `system-learning-hub/src/system_learning/ml_integrity/__main__.py` | ML integrity runner | ACTIVE |
| `system-learning-hub/run_hub.py` | Hub runner | ACTIVE |

---

## 6. Workbench Scripts

| File | Entry | Status |
|------|-------|--------|
| `Workbench/src/workbench/workspace/build_system_index.py` | System index builder | ACTIVE |
| `Workbench/src/workbench/workspace/promote_snapshot.py` | Snapshot promotion | ACTIVE |
| `Workbench/src/workbench/workspace/system_status.py` | System status | ACTIVE |
| `Workbench/src/workbench/workspace/list_latest.py` | List latest | ACTIVE |
| `Workbench/src/workbench/evidence_dashboard.py` | Evidence dashboard | ACTIVE |
| `Workbench/src/workbench/demo.py` | Demo runner | ACTIVE |
| `Workbench/src/workbench/artifact_navigator.py` | Artifact navigator | ACTIVE |
| `Workbench/src/workbench/contract_validator.py` | Contract validator | ACTIVE |
| `Workbench/src/workbench/c005_morphology_replay.py` | C005 morphology replay | ACTIVE |
| `Workbench/src/workbench/nlp.py` | NLP module | ACTIVE |
| `Workbench/src/ml/ml_signal_writer.py` | ML signal writer | ACTIVE |

---

## Orphaned Entry Points (Summary)

| File | Reason |
|------|--------|
| `scripts/_count_project.py` | One-off utility, no downstream consumers |
| `scripts/_test_fred_provider.py` | One-off test script |
| `check_candidates.py` | One-off candidate check |
| `check_panel.py` | One-off panel check |
| Various `__pycache__` bytecode | Build artifacts, not true entry points |
