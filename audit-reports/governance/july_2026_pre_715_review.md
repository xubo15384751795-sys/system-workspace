# Governance Pre-7/15 Review — 2026-07-03

**Reviewer:** System agent (scheduled `review_after` from `governance_freeze_manifest.yaml`)  
**Next review:** 2026-08-15

## 1. Governance freeze

| Check | Result |
|-------|--------|
| `scripts/check_governance_freeze.py` | Run after manifest/registry edits |
| Unapproved governance files | None expected — edits are to approved baseline files |
| `review_after` | Extended **2026-07-15 → 2026-08-15** |

**Decision:** Freeze continues. Post-freeze additions remain within `approved_additions_budget` (15 files).

## 2. Legacy data gateway (`retire_after`)

**Context:** `deformation-framework` read-only gateway shims carried `retire_after: 2026-07-15` (SEAL 2026-06-30).

| Option | Outcome |
|--------|---------|
| Hard retire 7/15 | Breaks archived `compute_proxies` imports and transitional research paths |
| **SEAL extend (chosen)** | Keep read-only shims; extend `retire_after` to **2026-10-15** |

**Rationale:** No active production consumer on legacy gateway; Harvester `benchmark_panel` is canonical. DuckDB migration (`duckdb_snapshot_store_migration`) still open through 7/31 — gateway removal is blocked on that evidence window.

## 3. `merged_data` migration (`deferred_work_register` deadline 7/15)

| Item | Status |
|------|--------|
| Active Python consumers of `Data/merged_data/` | **None** (only archived `compute_proxies.py`) |
| Canonical replacement | `Data/harvester/exports/latest/data/benchmark_panel.parquet` |
| `data_request_registry.merged_data_proxy_inputs` | **fulfilled_legacy** |
| `merged_data_harvester_consolidation` | **completed** — register closed; paths marked `archived_legacy` |

**Residual:** Files under `Data/merged_data/` retained for audit trail; `archive_after_days: 90` per updated retention policy.

## 4. Open deferred items (unchanged)

- `duckdb_snapshot_store_migration` — hard_deadline **2026-07-31**
- `capability_upgrade_master` — next review **2026-07-15** (wave progress ongoing)
- `pipeline_runner_import_migration` — evidence window through **2026-07-31**

## 5. Actions taken in this review

1. Extended governance freeze `review_after` to 2026-08-15.
2. Extended legacy gateway `retire_after` to 2026-10-15 (submodule).
3. Closed `merged_data_harvester_consolidation` in deferred work + data request registry.
4. Wired `evaluate_feedback_samples` weekly after `build_feedback_sample_pool`.
5. Added `archive_hmm_calibration_snapshot` for honest daily HMM history accumulation.
6. Fixed `NEXT_ACTIONS.md` / `improvement_queue.md` split — ledger-backed reports.
