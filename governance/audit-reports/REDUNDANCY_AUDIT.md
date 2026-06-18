# Redundancy Audit

Generated: 2026-06-03
Scope: All redundancy areas in `/Users/a1/System`

---

## Area 1: SigmaVector — 2 Implementations

### Implementation A: Class-based (Deformation)

| Field | Value |
|-------|-------|
| **File** | `Structural Deformation Research System/src/derivation/singular_detector.py` |
| **Class** | `SigmaVector` |
| **Type** | Python class with methods |
| **Used by** | `Structural Deformation Research System/src/output/output_exporter.py`, `Structural Deformation Research System/tests/test_singular_detector.py` |
| **Status** | Old path — persistence writes `{}` (empty) |

### Implementation B: Dict-based (Workbench)

| Field | Value |
|-------|-------|
| **File** | `Workbench/src/workbench/governance/semantic.py` |
| **Function** | `build_sigma_vector()` |
| **Type** | Returns plain dict `{"M": ..., "D": ..., "K": ..., "X": ...}` |
| **Used by** | `scripts/structural_replay_v2.py`, `scripts/bridge_replay_to_current.py`, `Workbench/tests/test_sigma_vector.py` |
| **Status** | Active path — produces real 4-channel data |

### Conflict

- Both produce a "SigmaVector" but with incompatible types (class vs dict).
- `singular_detector.py` `SigmaVector` class has `.to_dict()` but old Deformation run writes `{}`.
- `semantic.py` `build_sigma_vector()` is the canonical active implementation.
- Tests in `Workbench/tests/test_sigma_vector.py` validate the dict-based implementation.
- Tests in `Structural Deformation Research System/tests/test_singular_detector.py` validate the class-based implementation.

### Recommendation

Deprecate `singular_detector.py` `SigmaVector` class. Standardize on `semantic.py` dict-based implementation.

---

## Area 2: Z-Score — 10 Files

All files defining z-score computation functions:

| # | File | Function/Class | Notes |
|---|------|---------------|-------|
| 1 | `Structural Deformation Research System/src/data/data_sources.py` | `compute_z_score()` | Data sources module |
| 2 | `Structural Deformation Research System/src/derivation/proxy_builder.py` | `ProxyBuilder._z_score()` | Proxy builder internal |
| 3 | `Structural Deformation Research System/src/data/gateway/bridge.py` | `z_score_normalize()` | Gateway bridge |
| 4 | `Structural Deformation Research System/src/diagnostics/structural_diagnostic.py` | `StructuralDiagnostic._z_score()` | Diagnostic |
| 5 | `Structural Deformation Research System/src/diagnostics/residualization.py` | `residualize_z_score()` | Residualization |
| 6 | `Structural Deformation Research System/src/benchmarks/public_baselines.py` | `baseline_z_score()` | Public baselines |
| 7 | `Structural Deformation Research System/src/benchmarks/portfolio_baselines.py` | `portfolio_z_score()` | Portfolio baselines |
| 8 | `Structural Deformation Research System/src/benchmarks/institutional_risk.py` | `institutional_z_score()` | Institutional risk |
| 9 | `Structural Deformation Research System/src/core/models.py` | `ZScoreModel` | Core model |
| 10 | `scripts/archive/compute_proxies.py` | `compute_z_scores()` | ARCHIVED — script-level |

### Additional References (not definitions)

| File | Usage |
|------|-------|
| `Structural Deformation Research System/src/signals/fast_signal.py` | Imports z-score from models |
| `Structural Deformation Research System/src/data/snapshot_store.py` | Uses z-score for snapshot validation |
| `scripts/structural_replay_v2.py` | Uses z-score for replay computation |
| `scripts/structural_replay_evaluation.py` | Uses z-score for evaluation |
| `scripts/bridge_replay_to_current.py` | Uses z-score for bridge output |
| `scripts/_run_descriptive_quality_tests.py` | Uses z-score for quality tests |
| `paper-empirical-interface/src/paper_interface/attribution_engine.py` | Uses z-score for attribution |
| `Workbench/src/workbench/c005_morphology_replay.py` | Uses z-score for morphology |
| `tests/governance/test_c005_morphology_replay.py` | Tests z-score usage |
| `Structural Deformation Research System/src/data/quality/tier.py` | Quality tier z-score |

### Risk

- 10 different implementations may produce different z-score values for the same input.
- No single canonical z-score function exists.
- Divergent normalization (some use rolling window, some use full-sample, some use robust z-score).

### Recommendation

Extract a single canonical `z_score()` function in `Structural Deformation Research System/src/core/models.py` and have all other files import from it.

---

## Area 3: X_PRE / X_REALIZED — Deprecated References

These channels were deprecated but are still referenced across 22 files.

### Definition Files

| File | Role |
|------|------|
| `Structural Deformation Research System/src/derivation/singular_detector.py` | Defines X_PRE, X_REALIZED in SigmaVector |
| `Structural Deformation Research System/src/derivation/proxy_builder.py` | ProxyBuilder includes X_PRE/X_REALIZED in `MEASUREMENT_CHANNELS` |
| `Structural Deformation Research System/src/derivation/structural_layers.py` | References X_PRE/X_REALIZED in layer definitions |
| `Structural Deformation Research System/src/core/models.py` | Model references |
| `Structural Deformation Research System/src/output/output_exporter.py` | Exports X_PRE/X_REALIZED |
| `Structural Deformation Research System/src/proxies/__init__.py` | Proxy module init |
| `Structural Deformation Research System/src/proxies/x_shadow_accumulation.py` | Shadow accumulation proxy |

### Test Files

| File | Role |
|------|------|
| `Structural Deformation Research System/tests/test_proxy_builder.py` | Tests X_PRE/X_REALIZED |
| `Structural Deformation Research System/tests/test_singular_detector.py` | Tests SigmaVector with X_PRE/X_REALIZED |
| `Structural Deformation Research System/tests/test_output_exporter.py` | Tests export with X_PRE/X_REALIZED |
| `Structural Deformation Research System/tests/test_structural_layers.py` | Tests structural layers |
| `Workbench/tests/test_sigma_vector.py` | Tests SigmaVector (may reference) |
| `Workbench/tests/test_ml_governance_signal.py` | Tests ML governance signal |

### Consumer Files

| File | Usage |
|------|-------|
| `Workbench/src/workbench/governance/semantic.py` | May reference deprecated channels |
| `Workbench/src/workbench/c005_morphology_replay.py` | C005 morphology replay |
| `tests/governance/test_canonical_proxy_alignment.py` | Canonical proxy alignment test |
| `tests/governance/test_semantic_registry.py` | Semantic registry test |
| `tests/governance/test_c005_morphology_replay.py` | C005 morphology test |
| `tests/governance/anti_gaming/test_fake_proxy_semantic_abuse.py` | Anti-gaming test |
| `scripts/structural_replay_v2.py` | Structural replay |
| `scripts/wiki_system_bridge_audit.py` | Wiki bridge audit |
| `scripts/_run_descriptive_quality_tests.py` | Quality tests |

### Impact

- `ProxyBuilder.build_proxies()` returns `None` for X_PRE/X_REALIZED.
- All channels show `PROXY_REDUCED distance=3` because of this.
- 22 files still reference these deprecated channels.

### Recommendation

1. Remove X_PRE/X_REALIZED from `ProxyBuilder.MEASUREMENT_CHANNELS`.
2. Update all 22 files to use X (the active channel) instead.
3. Add deprecation warnings in any remaining references.

---

## Area 4: framework_output — 7 Writers

Seven files write `framework_output.json`, creating divergent schema risk.

| # | File | Function | Schema | Status |
|---|------|----------|--------|--------|
| 1 | `scripts/bridge_replay_to_current.py` | `bridge_to_framework_output()` | ACTIVE_FULL | ✅ Active, canonical |
| 2 | `scripts/refresh_output_current.py` | `refresh_current()` | Stale run data | ⚠️ PARTIAL |
| 3 | `scripts/structural_replay_evaluation.py` | `write_evaluation_output()` | Evaluation schema | ⚠️ Different schema |
| 4 | `Workbench/src/workbench/current.py` | `update_current()` | Workbench schema | ⚠️ Different schema |
| 5 | `Workbench/src/workbench/openbb_secondary_audit.py` | `write_audit_output()` | Audit schema | ⚠️ Different schema |
| 6 | `Workbench/src/workbench/nlp.py` | `write_nlp_output()` | NLP schema | 📄 PAPER (no data) |
| 7 | `Workbench/agents/harness/tools/workbench_tools.py` | `write_framework_output()` | Tool schema | ⚠️ Different schema |

### Schema Divergence Risk

- Each writer may produce a different JSON structure.
- `bridge_replay_to_current.py` produces `ACTIVE_FULL` with 4-channel data.
- `refresh_output_current.py` links to stale Deformation run.
- `structural_replay_evaluation.py` produces evaluation-specific fields.
- No shared schema contract exists for `framework_output.json`.

### Recommendation

1. Define a canonical `framework_output.schema.json` contract.
2. Make `bridge_replay_to_current.py` the sole writer (or merge all writers into one).
3. Add schema validation on write.

---

## Area 5: Proxy Direction — 2 Files

Two files implement proxy direction computation with different approaches.

| # | File | Function | Approach |
|---|------|----------|----------|
| 1 | `Structural Deformation Research System/src/signals/fast_signal.py` | `compute_direction()` | Signal-based direction |
| 2 | `Structural Deformation Research System/src/output/output_exporter.py` | `export_direction()` | Export-time direction |

### Additional References

| File | Usage |
|------|-------|
| `Structural Deformation Research System/src/data/snapshot_store.py` | Direction in snapshots |
| `Structural Deformation Research System/src/core/pipeline.py` | Pipeline direction computation |
| `Structural Deformation Research System/src/mechanisms/base.py` | Mechanism direction |
| `Structural Deformation Research System/src/operators/operator_algebra.py` | Operator direction |
| `Structural Deformation Research System/src/ui/components/state_cards.py` | UI direction display |
| `Structural Deformation Research System/src/ui/components/research_log_panel.py` | Research log direction |
| `Structural Deformation Research System/src/ui/components/paper_dashboard.py` | Paper dashboard direction |
| `Structural Deformation Research System/src/runtime/system_api.py` | System API direction |
| `Structural Deformation Research System/src/output/run_package.py` | Run package direction |
| `Structural Deformation Research System/src/interpretation/market_state.py` | Market state direction |
| `Workbench/agents/harness/entrypoints/deformation_cli.py` | CLI direction |
| `Workbench/agents/harness/skills/deformation-snapshot-audit/SKILL.md` | Audit skill direction |
| `Workbench/agents/harness/agents/math-auditor.md` | Math auditor direction |

### Risk

- Two different direction computations may produce conflicting results.
- `fast_signal.py` computes direction at signal time.
- `output_exporter.py` recomputes direction at export time.
- If they use different normalization windows, results will diverge.

### Recommendation

1. Single canonical `compute_direction()` function.
2. Remove duplicate from `output_exporter.py`.
3. Import from `fast_signal.py` or a shared utility.
