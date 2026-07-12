# Governance Layer Health Examination

**Date:** 2026-07-03 (UTC+8)  
**Scope:** `governance/`, pipeline registries, promotion topology, Learning Hub governance artifacts, CI gates  
**Constitution:** Not modified — this report is read-only diagnostic  
**Evidence sources:** `governance_status.json`, `governance_drag_report.json`, `architecture_reality_audit.json`, `output_routing_report.json`, `deferred_work_register.yaml`, live tool runs

---

## Executive Summary

| Dimension | Grade | Score / Status |
|-----------|-------|----------------|
| **Operational integrity** | A | Daily pipeline succeeds; run trace PASS; freeze check OK |
| **Topology / promotion** | D | `overall_status: BLOCKED`; cannot enter `current` or affect core judgment |
| **Complexity (drag)** | C+ | **32.3/80** MEDIUM — daily steps at target (25); scripts/tests still heavy |
| **Architecture compliance** | A- | 16/17 audit checks PASS; 1 WARN |
| **Registry hygiene** | B+ | 70 entrypoints archived; freeze budget **full** (15/15) |
| **Deferred debt** | C | 8 open items; 2 hard deadlines in July 2026 |
| **Learning governance loop** | C- | Hub wired; calibration gaps; stale human reports |

**Headline:** Governance is **working as designed** — the system runs reliably but **refuses promotion** until HMM model health and confidence evidence improve. Complexity reduction on the daily path succeeded (34→25 steps); structural debt remains in root scripts and untested entrypoints.

---

## 1. Governance Stack Map

```
┌─────────────────────────────────────────────────────────────────┐
│  Constitution / system_constitution.yaml (unchanged core)        │
├─────────────────────────────────────────────────────────────────┤
│  Freeze layer: governance_freeze_manifest.yaml                   │
│    review_after: 2026-08-15 | baseline hashes | additions 15/15  │
├─────────────────────────────────────────────────────────────────┤
│  Registries (SSOT)                                               │
│    daily_run_sequence.yaml ──► daily_run.py (71 steps, 25 daily) │
│    daily_pipeline_registry.yaml (76 steps, 22 weekly-tagged)     │
│    entrypoint_registry.yaml (185 scripts, 104 active)            │
│    authority_registry.yaml | data_request_registry.yaml          │
│    capability_registry.yaml | deferred_work_register.yaml        │
│    output_routing_policy.yaml                                    │
├─────────────────────────────────────────────────────────────────┤
│  Runtime gates                                                   │
│    promotion_gate ──► claim_ladder ──► output/current publish    │
│    authority_graph | freshness_validator | risk_gate             │
├─────────────────────────────────────────────────────────────────┤
│  Hub memory: governance_status | improvement_queue.parquet       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Operational Integrity ✅

### 2.1 Daily pipeline

| Metric | Value |
|--------|-------|
| Latest run | `daily_pipeline_20260703_063149_12180b` |
| Steps executed (last full run) | 32 success / 0 failed |
| Post-slim daily target | **25** (verified via `_daily_run_sequence`) |
| Weekly steps | 46 |
| Automation | `com.system.daily-run` launchd @ 07:00 local |

**Note:** Last bundled run predates 2026-07-03 slim commit; next launchd run will skip 9 newly-weekly steps → expect ~23–25 executed steps and shorter runtime (notably without `refresh_cross_asset_panel` daily).

### 2.2 Run trace & authority graph

| Check | Status |
|-------|--------|
| `run_trace.status` | PASS |
| `authority_graph.invariants_valid` | true |
| `drift_count` | 0 |
| `violation_count` | 0 |
| `exempt_drift_count` | 14 (documented diagnostic readouts) |

### 2.3 Exceptions register

| Metric | Value |
|--------|-------|
| Open exceptions | 0 |
| Overdue | 0 |
| Topology review items | 0 |

### 2.4 CI / automated governance tests

| Layer | Coverage |
|-------|----------|
| Per-push | `ci.yml` — pre-commit, lint, module tests, integration |
| Weekly | `weekly-governance.yml` — freeze, authority graph, dry-run, architecture audit |
| Governance-focused tests | ~14+ dedicated files (`test_governance_freeze`, `test_governance_status`, `tests/governance/*`, anti-gaming suite) |
| Full suite | 828 tests collected |

**Verdict:** Engineering governance is **healthy**. Failures are evidence-gated, not operational.

---

## 3. Promotion Topology ❌ (By Design)

### 3.1 Current gate state

```json
overall_status: BLOCKED
claim_ceiling: diagnostic_watch_only
can_enter_current: false
can_affect_core_judgment: false
can_affect_trade_decision: false
risk_gate: APPROVED_FOR_RESEARCH
```

### 3.2 Gate breakdown

| Gate | Status | Reason |
|------|--------|--------|
| **hmm** | BLOCKED | `model_health: FAIL` — posterior entropy 0.0045 < 0.01 (degenerate posterior) |
| **confidence** | WATCH | Low trade confidence; mechanism_confidence medium |
| k_gate | PASS | diagnostic_rebuild |
| x_gate | PASS | background_allowed |
| caselab | PASS (usable) | top_score 0.5575 |

### 3.3 HMM dual blocker (calibration vs health)

| Dimension | Status | Detail |
|-----------|--------|--------|
| Model health | **FAIL** | Blocks promotion **first** in `check_hmm()` |
| Calibration history | **INSUFFICIENT** | compatible_history_length: **1** / 10 required |
| Archive pipeline | Wired | `archive_hmm_calibration_snapshot` daily after `regime_detection` |

**Interpretation:** Even with 10 days of snapshots, promotion remains blocked until **posterior entropy** issue is resolved in the ML layer. Governance is not malfunctioning — it is enforcing separation between "runs" and "trust."

### 3.4 Claim ladder

| Field | Value |
|-------|-------|
| Current tier | 1 — mechanism_hypothesis |
| Upgrade to tier 2 | Requires M/D direction persisted ≥ **2 runs** (currently **0**) |
| Judgment decision | WATCH_ONLY, confidence low |

### 3.5 Forbidden vs allowed language (promotion envelope)

**Allowed:** diagnostic, watch, observation, measurement, analogy, structural similarity…  
**Forbidden:** regime, crisis, compression, signal, forecast, position, mechanism (in promoted surface), prediction…

---

## 4. Complexity & Slimming (Drag Assessment)

### 4.1 Scorecard (`governance_drag_report.json`)

| Component | Score /10 | Metric | Target |
|-----------|-----------|--------|--------|
| daily_step_drag | **2.5** | 25 daily steps | ≤25 ✅ |
| root_script_drag | 8.3 | 110 root `.py` scripts | ≤35 (deferred) |
| governance_file_drag | 7.5 | 30 governance YAMLs | consolidate |
| registry_drag | 0 | authority registry entries | OK |
| untested_drag | **10** | 78 scripts without tests | worst bucket |
| orphan_drag | 2 | 2 orphan Output dirs | low |
| hash_reconcile_drag | 0 | — | OK |
| governance_ratio_drag | 2 | 30% commits governance (last 10) | acceptable |
| **TOTAL** | **32.3 / 80** | MEDIUM | **< 25** goal |

### 4.2 Slimming actions completed (2026-07-03)

Moved **9 steps** daily → weekly:

`build_policy_from_paper`, `run_operator_detections`, `measurement_quality_report`, `build_data_gaps`, `refresh_cross_asset_panel`, `evaluate_pending`, `judgment_accuracy_report`, `evidence_grade_report`, `build_artifact_registry`

`pipeline_schedule.md` synced as human-readable SSOT mirror.

### 4.3 Remaining compression opportunities (no constitution change)

| Priority | Action | Expected drag impact |
|----------|--------|---------------------|
| P1 | Archive orphan root scripts → `scripts/archive/` | −3 to −5 root_script_drag |
| P2 | Tests for 25 daily signal-blocking scripts only | −4 to −6 untested_drag |
| P3 | Merge registry duplication (sequence + pipeline + entrypoint descriptions) | −1 governance_file_drag |
| P4 | Callable migration (15/76 today) | reduces subprocess overhead, not drag score directly |

---

## 5. Freeze & Registry Hygiene

### 5.1 Governance freeze

| Check | Result |
|-------|--------|
| `check_governance_freeze.py` | **PASS** |
| `review_after` | 2026-08-15 |
| `approved_additions` | **15 / 15 (FULL)** ⚠️ |
| `work_support_budget` | 12 / 17 |
| Baseline hash integrity | Current (updated 2026-07-03) |

**Risk:** Next governance file addition requires either freeze review approval to bump budget or an existing file hash-only update path. Plan additions before 2026-08-15 review.

### 5.2 Entrypoint lifecycle

| Status | Count |
|--------|-------|
| active | 104 |
| archived | 70 |
| experimental | 3 |
| compatibility_wrapper | 3 |
| legacy_sealed | 1 |
| governance_active | 2 |

**Archive ratio:** 40% — healthy lifecycle discipline.

### 5.3 Pipeline registry

| Metric | Value |
|--------|-------|
| Registered steps | 76 |
| active | 68 |
| experimental | 3 |
| `schedule: weekly` in registry | 22 (not all weekly sequence steps tagged — sequence YAML is authoritative for `daily_run.py`) |
| Callable execution | 15 / 76 |

---

## 6. Architecture & Contract Audits

### 6.1 Architecture reality audit (2026-07-03 refresh)

| Check group | Result |
|-------------|--------|
| HTTP imports / API keys / legacy pipeline imports | PASS |
| Symlink freshness / required governance files | PASS |
| Evidence release schema / provider acquisition | PASS |
| Daily pipeline registry sync | PASS |
| Legacy deadline countdown | PASS (completed items filtered) |
| Data retention executor | PASS (documented gap: no `apply_data_retention_policy.py`) |
| **manual_sys_path_insert** | **WARN** — 1 finding |

**Open finding:**

- `scripts/refresh_improvement_queue_report.py:23` — `sys.path.insert` for Hub import (should use `_workspace_imports` pattern like other scripts)

### 6.2 Output routing audit

| Finding | Detail |
|---------|--------|
| `operator_activations.json` | Present in `Output/current/` but **not** in `output_routing_policy.groups.current.allowed_artifacts` |

**Fix options:** Register artifact in routing policy (if intentional current readout) or move to sandbox/research group.

### 6.3 Supervisor policy

| Metric | Value |
|--------|-------|
| supervisor_status | WARN |
| review_items | 1 |

(Tied to promotion / evidence review queue — not a pipeline failure.)

---

## 7. Deferred Work & Deadlines

### 7.1 Status distribution

| Status | Count |
|--------|-------|
| completed | 3 |
| completed_sealed | 1 |
| in_progress | 3 |
| deferred | 5 |

### 7.2 Open items (action calendar)

| ID | Status | Hard deadline | Notes |
|----|--------|---------------|-------|
| duckdb_snapshot_store_migration | deferred | **2026-07-31** | 46MB legacy store; blocks gateway retirement |
| submodule_consolidation_plan | deferred | **2026-07-31** | CI still uses submodule checkout |
| capability_upgrade_master | in_progress | 2026-09-01 | P1–P4 waves |
| pipeline_runner_import_migration | in_progress | 2026-08-15 | 15/76 callable |
| callable_e2e_pipeline_tests | in_progress | 2026-08-15 | blocked_by runner migration |
| root_scripts_pipeline_refactoring | deferred | 2026-08-15 | 110 scripts vs 35 target |
| dependency_locking | deferred | 2026-08-15 | — |
| p6_low_priority_improvements | deferred | 2026-09-01 | — |

### 7.3 Recently closed (2026-07-03)

- `merged_data_harvester_consolidation` → **completed**
- Legacy gateway `retire_after` → **2026-10-15** (SEAL extend)

---

## 8. Module Capability Posture (`capability_registry.yaml`)

| Status | Modules |
|--------|---------|
| **CANONICAL** | Workbench, Harvester, Protocols, Agent Routing (partial) |
| **ACTIVE_PARTIAL** | Deformation Framework, Data/Output, Learning Hub, CaseLab, NLP |
| **REAL_EXPERIMENTAL** | ML Signals, Backtest Lens, Qlib Benchmark |
| **PAPER_RETAIN** | Research Terminal |

**Framework blockers (documented):** legacy gateway shim still in public path until DuckDB migration evidence window closes.

---

## 9. Learning Hub & Calibration Governance

| Metric | Value | Gap |
|--------|-------|-----|
| judgment_calibration_evaluated | 12 | 0 |
| trade_decision_calibration_evaluated | 1 | **9** |
| hmm_calibration_history_count (Hub) | 0 | **10** (stale vs audit; re-ingest needed) |
| feedback_pending_count | 14 | — |
| feedback pool evaluated | 1313 | labels low-value / missed_stress heavy |
| improvement_queue (ledger) | 14 items | report refresh wired |
| learning_summary.md | **2026-06-18** | stale |

**Weekly learning chain (post 7/3):** `build_feedback_sample_pool` → `evaluate_feedback_samples` → `baseline_comparison` (Monday or `--force-weekly`).

---

## 10. Staleness & SSOT Drift

| Artifact | Issue |
|----------|-------|
| `governance_status.completed_steps` | Reflects pre-slim 32-step run; missing `archive_hmm_calibration_snapshot` |
| `capability_registry.yaml` gateway note | Still says `retire_after: 2026-07-15` (actual: 2026-10-15) |
| `learning_summary.md` | 15 days stale |
| Hub `hmm_calibration_history_count` | Not synced after audit `compatible_history_length` fix |
| `output_routing_report` | 2026-07-02; operator_activations unregistered |

**Recommendation:** Run `python3 scripts/governance_status.py` + `ingest_daily_run_to_hub.py` after next full weekly (`--force-weekly`) to refresh composite status.

---

## 11. Maturity vs Typical Production Platform

### What this project has (above average for research repos)

- Machine-checkable freeze with content hashes
- Promotion gate with claim-type-aware blocking
- Authority graph with invariant checks
- Dual-clock deferred work register
- Anti-gaming test suite
- Weekly governance CI workflow
- Automated daily orchestration (launchd)
- Hub ledger-backed improvement queue

### What mature production platforms add (gaps)

| Gap | Impact |
|-----|--------|
| Single deployable service / container | Harder onboarding & ops |
| Unified observability (metrics/tracing) | Debug via logs + JSON only |
| Submodule → monorepo | CI complexity, version drift |
| Promotion unblocked path | Product output stuck at diagnostic tier |
| Retention policy executors | Policy documented, not enforced by script |
| Freeze additions budget exhausted | Friction for next registry change |

---

## 12. Prioritized Action Plan

### Tier 0 — Evidence (unblocks promotion, not governance docs)

1. Fix HMM degenerate posterior (`Workbench/src/ml/`) — **only path to clear `hmm` BLOCKED**
2. Accumulate 10 compatible HMM daily snapshots (automatic via launchd)
3. Persist M/D direction 2+ runs for claim ladder tier 2

### Tier 1 — Governance hygiene (low risk)

4. Register `operator_activations.json` in `output_routing_policy.yaml` OR relocate output
5. Fix `refresh_improvement_queue_report.py` import pattern (clear architecture WARN)
6. Update `capability_registry.yaml` gateway retire_after note → 2026-10-15
7. Re-run weekly pipeline + hub ingest to refresh `governance_status` / `summary.json`

### Tier 2 — Compression (optional, post Tier 1)

8. Archive batch of unused root scripts (target −20 files)
9. Add tests for 25 daily signal-blocking scripts
10. Plan freeze budget bump at 2026-08-15 review (additions 15→18?)

### Tier 3 — Structural debt (July–August deadlines)

11. DuckDB snapshot store migration (by 2026-07-31)
12. Submodule consolidation plan execution or formal fallback acceptance
13. Callable runner migration completion (by 2026-08-15)

---

## 13. Conclusion

The governance layer is **not broken** — it is **strict**. Operational gates pass; promotion gates intentionally fail until ML health and calibration evidence meet written thresholds. The 2026-07-03 slimming achieved the daily-step target and reduced drag on the hottest path; remaining complexity lives in script surface area and test coverage, not in daily orchestration bloat.

**Next governance review:** 2026-08-15 (`governance_freeze_manifest.review_after`)

---

*Generated by governance health examination. Re-run diagnostics:*

```bash
python3 scripts/governance_status.py
python3 scripts/build_governance_drag_report.py
python3 scripts/architecture_reality_audit.py
python3 scripts/check_governance_freeze.py
```
