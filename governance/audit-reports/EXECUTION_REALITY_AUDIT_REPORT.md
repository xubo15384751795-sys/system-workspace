# Execution Reality Audit Report

**Generated:** 2026-06-02
**Scope:** Full Structural Deformation Research System

---

## Executive Summary

The system has **6 REAL capabilities** and **6 PAPER capabilities**. The REAL chain is: Harvester → Replay → SigmaVector → framework_output → ./sys check. This chain works end-to-end with real data. The PAPER capabilities are code that exists and tests pass, but no real data flows through them.

**Critical finding:** The Deformation run path (the "official" path) is BROKEN — it produces output but SigmaVector is empty `{}`. The system works only because a bridge script (`bridge_replay_to_current.py`) bypasses the broken path.

---

## Risk Register

### P0 — System Output Un可信

| ID | Issue | Evidence | Affected Files | Impact | Action |
|----|-------|----------|---------------|--------|--------|
| P0-1 | **Deformation run SigmaVector persistence is empty** | `Output/deformation_runs/2026-04-22_WEEKLY/machine/snapshot.json` has `sigma_vector: {}` | `singular_detector.py` → `output_exporter.py` → snapshot | Detector computes SigmaVector but it's not persisted. Any consumer reading from Deformation run gets empty data. | Fix snapshot persistence in `output_exporter.py` or Deformation run pipeline. |
| P0-2 | **refresh_output_current.py links to stale run** | `Output/current/latest_run` → `2026-04-22_WEEKLY` (6 weeks old) | `scripts/refresh_output_current.py` | `./sys check` without bridge shows UNKNOWN. Evidence dashboard shows stale data. | Run bridge after each replay, or fix Deformation run frequency. |
| P0-3 | **NLP pipeline has no data** | `Workbench/src/nlp/` has 48 files but no corpus data. `candidate_ledger.py` produces no entries. | `Workbench/src/nlp/*.py` | NLP capabilities (event extraction, case similarity, narrative drift) are documented but non-functional. | Either connect corpus data or mark NLP as experimental. |
| P0-4 | **Learning Hub has no runtime events** | `system-learning-hub/` has 1 git commit. No runtime events in `Output/system_learning/`. | `system-learning-hub/src/system_learning/` | Governance memory, improvement queue, system health are documented but non-functional. | Either generate runtime events or mark Learning Hub as experimental. |

### P1 — Capability 夸大

| ID | Issue | Evidence | Affected Files | Impact | Action |
|----|-------|----------|---------------|--------|--------|
| P1-1 | **All channels PROXY_REDUCED distance=3** | `governance/semantic_registry.json` — all 4 channels have `semantic_distance: 3` | `semantic_registry.json` | Every channel measures something *related to* the canonical concept, not the canonical concept itself. M uses NFCI (broad composite) for anchor mismatch. | Document honestly. Do not upgrade confidence until proxy quality improves. |
| P1-2 | **ProxyBuilder MEASUREMENT_CHANNELS includes deprecated X_PRE/X_REALIZED** | `proxy_builder.py` L15: `MEASUREMENT_CHANNELS = ("M", "D", "K", "X_PRE", "X_REALIZED")` | `proxy_builder.py` | ProxyBuilder computes X_PRE/X_REALIZED which are deprecated. In last run, both are None. | Remove X_PRE/X_REALIZED from MEASUREMENT_CHANNELS. Use X_agg. |
| P1-3 | **7 files write framework_output** | `current.py`, `openbb_secondary_audit.py`, `nlp.py`, `workbench_tools.py`, `bridge_replay_to_current.py`, + 2 tests | Multiple | Risk of divergent schemas. Each writer may produce different framework_output shape. | Consolidate to single writer. |
| P1-4 | **Backtest Lens is PAPER** | `scripts/run_historical_replay.py` and `scripts/run_allocation_backtest.py` exist but produce no artifacts | `scripts/run_historical_replay.py`, `scripts/run_allocation_backtest.py` | Documented as capability but non-functional. | Either wire to output or mark as experimental. |

### P2 — 维护风险

| ID | Issue | Evidence | Impact | Action |
|----|-------|----------|--------|--------|
| P2-1 | **Two SigmaVector implementations** | `singular_detector.py` (dataclass) + `semantic.py` (dict-based) | Risk of divergence. Phase 1-4 fixed singular_detector but semantic.py is independent. | Keep both — they serve different purposes (runtime vs governance). Document the split. |
| P2-2 | **10 files define z-score functions** | `proxy_builder.py`, `fast_signal.py`, `historical_replay.py`, `institutional_risk.py`, `portfolio_baselines.py`, etc. | Different window/winsor params. Risk of inconsistent normalization. | Consolidate to shared utility. |
| P2-3 | **102 fallback references in production** | `structural_replay_v2.py`, `current.py`, `evidence_dashboard.py`, etc. | Fallbacks mask failures. System may report success when using fallback data. | Audit each fallback — some are legitimate (graceful degradation), some are dangerous (silent failure). |
| P2-4 | **241 return_none in production** | Across all modules | Callers must handle None. Risk of AttributeError or silent failure. | Acceptable pattern but needs consistent None-handling in callers. |

### P3 — 清理项

| ID | Issue | Evidence | Action |
|----|-------|----------|--------|
| P3-1 | **X_PRE/X_REALIZED deprecated but heavily referenced** | 22 files reference X_PRE/X_REALIZED | Gradually remove references. Keep in ProxyReading for backward compat. |
| P3-2 | **13 TODO/FIXME in production code** | Various files | Address or remove. |
| P3-3 | **Orphan entry points** | `_count_project.py`, `_test_fred_provider.py`, `check_candidates.py`, `check_panel.py` | Delete or archive. |
| P3-4 | **Placeholder in Qlib runner** | `ExternalTools/qlib_benchmark_runner/run_qlib_benchmark.py` L140 | Either install Qlib or mark as optional. |

---

## Top 3 Highest Priority Fixes

### 1. Fix Deformation Run SigmaVector Persistence (P0-1)

**Problem:** The Deformation run pipeline computes SigmaVector but doesn't persist it in the snapshot. `Output/deformation_runs/2026-04-22_WEEKLY/machine/snapshot.json` has `sigma_vector: {}`.

**Root cause:** The Deformation run uses `output_exporter.py` which reads `sigma_vector` from `snapshot.state.provenance.singular_detector.sigma_vector` — but the run doesn't populate this path.

**Fix:** Either:
- (a) Fix the Deformation run to populate `provenance.singular_detector.sigma_vector` in the snapshot
- (b) Or accept the bridge as the permanent path and remove the broken Deformation run path

**Files:** `singular_detector.py`, `output_exporter.py`, Deformation run pipeline

### 2. Consolidate framework_output Writers (P1-3)

**Problem:** 7 files write `framework_output.json`. Each may produce a different schema shape.

**Fix:** Single writer function in `Workbench/src/workbench/current.py`. All other paths call this function.

**Files:** `current.py`, `openbb_secondary_audit.py`, `nlp.py`, `workbench_tools.py`, `bridge_replay_to_current.py`

### 3. Mark PAPER Capabilities Honestly (P0-3, P0-4)

**Problem:** NLP Pipeline and Learning Hub are documented as capabilities but have no data flowing through them.

**Fix:** Add explicit status markers:
- NLP Pipeline: `status: EXPERIMENTAL` in module docs
- Learning Hub: `status: EXPERIMENTAL` in module docs
- Remove from `./sys check` output until data flows

**Files:** `MODULES.md`, `module_contexts/nlp.md`, `module_contexts/learning-hub.md`

---

## What The System Actually Solves Today

1. **"What is the current structural risk state?"** → `./sys check` shows ACTIVE_FULL with 4-channel SigmaVector (M=-0.75, D=-0.88, K=-1.19, X_agg=-0.76)

2. **"Which channel is dominant?"** → K (low_vol_compression, abs 1.19)

3. **"Is there a measurement blind spot?"** → NO (4/4 channels live)

4. **"How did historical stress events look?"** → 16 events with 4-channel analysis. X_agg fires in 11/16, dominant in 5.

5. **"Are the proxies canonical?"** → All PROXY_REDUCED (distance=3). Governance tests enforce canonical alignment.

6. **"Is the data fresh?"** → Harvester release 2026-06-02-r8 with 42 series, 256K rows.

**What it does NOT solve today:**
- Real-time monitoring (batch only)
- NLP event extraction (no corpus)
- Governance memory (no runtime events)
- Backtesting (not wired)
- ML signal generation (not trained)
