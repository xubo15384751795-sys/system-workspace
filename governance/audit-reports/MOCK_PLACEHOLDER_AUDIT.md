# Mock & Placeholder Audit

Generated: 2026-06-03
Scope: All pattern matches for mock/placeholder/stub patterns in `/Users/a1/System`

---

## Summary by Severity

| Pattern | Total Matches | Production Files | Test Files | Severity |
|---------|---------------|------------------|------------|----------|
| `awaiting_data` | 25 | 19 | 6 | 🔴 HIGH |
| `diagnostic_only` | 33 | 29 | 4 | 🟡 MEDIUM |
| `fallback` | 257 | 102 | 155 | 🟡 MEDIUM |
| `not_implemented` / `NotImplemented` | 150 | 74 | 76 | 🔴 HIGH |
| `return None` | ~500 | 241 | ~259 | 🟡 MEDIUM |
| `return {}` | 33 | 33 | 0 | 🟡 MEDIUM |
| `placeholder` | 52 | 23 | 29 | 🟠 LOW |
| `hardcoded` | 16 | 6 | 10 | 🟠 LOW |

---

## 1. `awaiting_data` — 25 matches (19 production)

**Severity: 🔴 HIGH** — Production code explicitly waiting for data that doesn't exist.

### Production Files (19)

| File | Count | Context |
|------|-------|---------|
| `scripts/structural_replay_v2.py` | 14 | Event windows awaiting data for 14 historical events |
| `governance/semantic_registry.json` | 1 | Channel awaiting data |
| `governance/canonical_proxy_spec.yaml` | 3 | Proxy specs awaiting data |
| `governance/x_agg_v1_obs_procurement_plan.md` | 2 | X_agg procurement plan |

### Test Files (6)

| File | Count | Context |
|------|-------|---------|
| `tests/governance/test_canonical_proxy_alignment.py` | 3 | Tests for canonical proxy alignment |
| `scripts/wiki_system_bridge_audit.py` | 1 | Wiki bridge audit |

### Risk Assessment

The 14 `awaiting_data` in `structural_replay_v2.py` correspond to 14 historical event windows that need proxy data to be computed. These are **legitimate gaps** — the events exist but the proxy data hasn't been fetched/computed yet.

---

## 2. `diagnostic_only` — 33 matches (29 production)

**Severity: 🟡 MEDIUM** — Code paths used only for diagnostics, not production logic.

### Production Files (29)

| File | Count | Context |
|------|-------|---------|
| `scripts/structural_replay_v2.py` | 18 | Diagnostic-only event windows |
| `Structural Deformation Research System/src/dynamic/provider_integrity_panel.py` | 2 | Provider integrity diagnostics |
| `Structural Deformation Research System/src/dynamic/observation_integrity.py` | 4 | Observation integrity diagnostics |

### Test Files (4)

| File | Count | Context |
|------|-------|---------|
| `Structural Deformation Research System/tests/test_provider_integrity_panel.py` | 3 | Tests for provider integrity |
| `Structural Deformation Research System/tests/test_observation_integrity.py` | 3 | Tests for observation integrity |

### Risk Assessment

The 18 `diagnostic_only` in `structural_replay_v2.py` are event windows that produce diagnostic output but don't feed into the main pipeline. The 6 in `provider_integrity_panel.py` and `observation_integrity.py` are integrity checks. These are **intentional diagnostic code paths**.

---

## 3. `fallback` — 257 matches (102 production)

**Severity: 🟡 MEDIUM** — Fallback logic that may mask real errors.

### Top Production Files (102 total)

| File | Count | Context |
|------|-------|---------|
| `Structural Deformation Research System/src/data/data_sources.py` | 61 | Data source fallbacks (largest) |
| `Structural Deformation Research System/src/data/quality/manifest.py` | 16 | Quality manifest fallbacks |
| `Structural Deformation Research System/src/data/adapters/public_adapters.py` | 14 | Public adapter fallbacks |
| `scripts/structural_replay_v2.py` | 10 | Replay fallbacks |
| `Workbench/src/ml/gluonts_regime_forecaster.py` | 10 | ML forecaster fallbacks |
| `structural-risk-harvester/src/harvester/official.py` | 8 | Harvester official fallbacks |
| `structural-risk-harvester/src/harvester/providers/h41.py` | 8 | H41 provider fallbacks |
| `Structural Deformation Research System/src/data/gateway/data_hub.py` | 7 | Data hub fallbacks |
| `Structural Deformation Research System/src/data/gateway/bridge.py` | 11 | Bridge fallbacks |
| `Workbench/src/workbench/governance/report_gate.py` | 4 | Report gate fallbacks |
| `Workbench/src/nlp/embeddings/embedder.py` | 3 | NLP embedder fallbacks |
| `Workbench/src/ml/tft_regime_detector.py` | 3 | TFT detector fallbacks |
| `Structural Deformation Research System/src/diagnostics/morphology_classifier.py` | 2 | Morphology classifier fallbacks |
| `Workbench/src/ml/regime_detector.py` | 2 | Regime detector fallbacks |
| `Structural Deformation Research System/src/dynamic/temporal.py` | 1 | Temporal fallback |
| `Workbench/src/ml/governance_signal.py` | 1 | Governance signal fallback |
| `Structural Deformation Research System/config.yaml` | 4 | Config fallbacks |
| `Structural Deformation Research System/README.md` | 4 | Documentation references |

### Risk Assessment

- `data_sources.py` (61 matches) is the biggest concern — heavy fallback logic may mask data quality issues.
- `data/quality/manifest.py` (16 matches) — quality manifest has extensive fallback chains.
- `data/adapters/public_adapters.py` (14 matches) — public data adapters fall back silently.
- Most other fallbacks are **defensive programming** and acceptable.

---

## 4. `not_implemented` / `NotImplemented` — 150 matches (74 production)

**Severity: 🔴 HIGH** — Explicitly unimplemented features in production code.

### Top Production Files (74 total)

| File | Count | Context |
|------|-------|---------|
| `Structural Deformation Research System/src/data/data_sources.py` | 10 | Data source methods not implemented |
| `scripts/structural_replay_v2.py` | 10 | Replay methods not implemented |
| `Structural Deformation Research System/src/core/pipeline.py` | 10 | Pipeline methods not implemented |
| `Workbench/src/nlp/extraction/llm_extractor.py` | 8 | LLM extractor methods not implemented |
| `Structural Deformation Research System/src/operators/operator_algebra.py` | 1 | Operator algebra not implemented |
| `Structural Deformation Research System/src/operators/operator_registry.py` | 4 | Operator registry not implemented |
| `Structural Deformation Research System/src/operators/event_to_operator.py` | 5 | Event-to-operator not implemented |
| `Structural Deformation Research System/src/operators/operator_diagnostics.py` | 4 | Operator diagnostics not implemented |
| `Workbench/src/workbench/evidence_dashboard.py` | 3 | Evidence dashboard not implemented |
| `Workbench/src/workbench/openbb_secondary_audit.py` | 3 | OpenBB audit not implemented |
| `Structural Deformation Research System/src/data/gateway/bridge.py` | 4 | Gateway bridge not implemented |
| `Structural Deformation Research System/src/data/gateway/data_hub_lite.py` | 2 | Data hub lite not implemented |
| `Structural Deformation Research System/src/data/gateway/evidence_router.py` | 1 | Evidence router not implemented |
| `Structural Deformation Research System/src/data/contracts.py` | 3 | Data contracts not implemented |
| `Structural Deformation Research System/src/data/snapshot_store.py` | 7 | Snapshot store not implemented |
| `Structural Deformation Research System/src/validation/unconditional_evaluator.py` | 1 | Unconditional evaluator not implemented |
| `Structural Deformation Research System/src/validation/forward_targets.py` | 1 | Forward targets not implemented |
| `Workbench/src/workbench/nlp.py` | 2 | NLP not implemented |
| `Workbench/src/workbench/governance/routing_gate.py` | 2 | Routing gate not implemented |
| `Workbench/src/ml/graph_embed.py` | 1 | Graph embedding not implemented |
| `Structural Deformation Research System/src/output/output_exporter.py` | 2 | Output exporter not implemented |
| `scripts/wiki_system_bridge_audit.py` | 2 | Wiki bridge audit not implemented |
| `Structural Deformation Research System/src/core/calibration.py` | 1 | Calibration not implemented |
| `Structural Deformation Research System/src/ml/dl_anomaly_detector.py` | 2 | DL anomaly detector not implemented |
| `Structural Deformation Research System/src/core/representation/graph_repr.py` | 1 | Graph representation not implemented |
| `Structural Deformation Research System/src/dynamic/provider_integrity_panel.py` | 6 | Provider integrity not implemented |
| `Workbench/src/workbench/workspace/build_system_index.py` | 5 | System index not implemented |
| `Workbench/src/workbench/workspace/promote_snapshot.py` | 2 | Snapshot promotion not implemented |
| `Workbench/src/workbench/workspace/system_status.py` | 2 | System status not implemented |
| `Workbench/src/workbench/workspace/list_latest.py` | 2 | List latest not implemented |
| `Workbench/src/workbench/freshness.py` | 4 | Freshness not implemented |
| `Workbench/src/workbench/framework_registry.py` | 1 | Framework registry not implemented |

### Risk Assessment

- **P0**: `data_sources.py` (10), `pipeline.py` (10) — core pipeline has unimplemented methods.
- **P1**: `llm_extractor.py` (8) — NLP extraction is PAPER.
- **P1**: `operator_*.py` (14 total) — operator algebra largely unimplemented.
- **P2**: `snapshot_store.py` (7) — snapshot store has unimplemented methods.
- Most are `raise NotImplementedError` stubs — they'll fail loudly if called.

---

## 5. `return None` — ~500 matches (241 production)

**Severity: 🟡 MEDIUM** — Silent failure via None return.

### Top Production Files (241 total)

| File | Count | Context |
|------|-------|---------|
| `Structural Deformation Research System/src/core/pipeline.py` | 10 | Pipeline returns None |
| `Structural Deformation Research System/src/data/data_sources.py` | 10 | Data sources return None |
| `structural-risk-harvester/src/harvester/derived.py` | 8 | Harvester derived returns None |
| `Structural Deformation Research System/src/data/snapshot_store.py` | 7 | Snapshot store returns None |
| `system-learning-hub/src/system_learning/ml_integrity/pollution_monitor.py` | 6 | Pollution monitor returns None |
| `Structural Deformation Research System/src/dynamic/provider_integrity_panel.py` | 6 | Provider integrity returns None |
| `research_terminal/data/router.py` | 5 | Research terminal returns None |
| `Workbench/src/workbench/workspace/build_system_index.py` | 5 | System index returns None |
| `paper-empirical-interface/src/paper_interface/attribution_engine.py` | 4 | Attribution engine returns None |
| `Structural Deformation Research System/src/operators/operator_registry.py` | 4 | Operator registry returns None |
| `Structural Deformation Research System/src/operators/operator_diagnostics.py` | 4 | Operator diagnostics returns None |
| `Workbench/src/workbench/freshness.py` | 4 | Freshness returns None |
| `Structural Deformation Research System/src/operators/event_to_operator.py` | 5 | Event-to-operator returns None |
| `Structural Deformation Research System/src/data/gateway/bridge.py` | 4 | Gateway bridge returns None |
| `structural-risk-harvester/src/harvester/providers/sec.py` | 3 | SEC provider returns None |
| `Workbench/src/workbench/evidence_dashboard.py` | 3 | Evidence dashboard returns None |
| `Workbench/src/workbench/openbb_secondary_audit.py` | 3 | OpenBB audit returns None |
| `Structural Deformation Research System/src/data/contracts.py` | 3 | Data contracts return None |
| `system-learning-hub/src/system_learning/runtime/manifest.py` | 2 | Manifest returns None |
| `Workbench/src/nlp/extraction/llm_extractor.py` | 8 | LLM extractor returns None |
| `Structural Deformation Research System/src/output/output_exporter.py` | 2 | Output exporter returns None |
| `Workbench/src/workbench/governance/routing_gate.py` | 2 | Routing gate returns None |
| `Workbench/src/workbench/workspace/promote_snapshot.py` | 2 | Snapshot promotion returns None |
| `Workbench/src/workbench/workspace/system_status.py` | 2 | System status returns None |
| `Workbench/src/workbench/workspace/list_latest.py` | 2 | List latest returns None |
| `Structural Deformation Research System/src/ml/dl_anomaly_detector.py` | 2 | DL anomaly detector returns None |
| `Workbench/src/nlp/embeddings/embedder.py` | 2 | NLP embedder returns None |

### Risk Assessment

- `return None` is the **most pervasive pattern** (241 production matches).
- Many are **legitimate optional returns** (e.g., "no data available" → None).
- Some are **silent failures** that should raise exceptions instead.
- The 10 in `pipeline.py` and 10 in `data_sources.py` are the most concerning — core pipeline silently returns None.

---

## 6. `return {}` — 33 matches (33 production)

**Severity: 🟡 MEDIUM** — Empty dict returns that may mask missing data.

### Production Files (33)

| File | Count | Context |
|------|-------|---------|
| `Structural Deformation Research System/src/data/gateway/bridge.py` | 2 | Gateway bridge returns {} |
| `Structural Deformation Research System/src/data/gateway/data_hub_lite.py` | 1 | Data hub lite returns {} |
| `Structural Deformation Research System/src/core/models.py` | 2 | Core models return {} |
| `Structural Deformation Research System/src/simulation/case_studies.py` | 1 | Case studies return {} |
| `Structural Deformation Research System/src/ui/run_viewer.py` | 2 | Run viewer returns {} |
| `Structural Deformation Research System/src/runtime/assembly.py` | 1 | Assembly returns {} |
| `Structural Deformation Research System/src/ml/detector_factory.py` | 1 | Detector factory returns {} |
| `Structural Deformation Research System/src/diagnostics/structural_diagnostic.py` | 1 | Structural diagnostic returns {} |
| `Workbench/src/workbench/current.py` | 1 | Current returns {} |
| `Workbench/src/workbench/artifact_navigator.py` | 2 | Artifact navigator returns {} |
| `Workbench/src/workbench/c005_morphology_report.py` | 3 | C005 report returns {} |
| `Workbench/src/workbench/workspace/promote_snapshot.py` | 1 | Snapshot promotion returns {} |
| `Workbench/agents/harness/events/event_consumer.py` | 2 | Event consumer returns {} |
| `Workbench/agents/harness/hooks/pre_tool_use.py` | 1 | Pre-tool-use returns {} |
| `Workbench/agents/harness/tools/task_router.py` | 2 | Task router returns {} |
| `Workbench/agents/harness/tools/workbench_tools.py` | 1 | Workbench tools returns {} |
| `Workbench/agents/harness/tools/deformation_tools.py` | 4 | Deformation tools returns {} |
| `Workbench/agents/harness/policies/feature_flags.py` | 1 | Feature flags returns {} |
| `scripts/structural_replay_v2.py` | 1 | Structural replay returns {} |
| `scripts/bridge_replay_to_current.py` | 1 | Bridge returns {} |
| `system-learning-hub/src/system_learning/schema.py` | 1 | Schema returns {} |
| `system-learning-hub/src/system_learning/analyzers/recurrence.py` | 1 | Recurrence returns {} |

### Risk Assessment

- `deformation_tools.py` (4 matches) — agent harness tools return empty dicts on failure.
- `c005_morphology_report.py` (3 matches) — morphology report returns empty on missing data.
- `event_consumer.py` (2 matches) — event consumer returns empty on missing events.
- Most are **defensive returns** — acceptable if callers check for empty dict.

---

## 7. `placeholder` — 52 matches (23 production)

**Severity: 🟠 LOW** — Placeholder code/comments.

### Production Files (23)

| File | Count | Context |
|------|-------|---------|
| `ExternalTools/qlib_benchmark_runner/run_qlib_benchmark.py` | 12 | Qlib benchmark placeholders |
| `Structural Deformation Research System/config.yaml` | 3 | Config placeholders |
| `Workbench/src/workbench/governance/report_gate.py` | 4 | Report gate placeholders |
| `Workbench/contracts/workbench/framework_contract.schema.json` | 1 | Schema placeholder |
| `Workbench/src/benchmarks/market_feedback/sandbox_exporter.py` | 2 | Sandbox exporter placeholders |
| `Workbench/src/ml/governance_signal.py` | 1 | Governance signal placeholder |

### Risk Assessment

- `run_qlib_benchmark.py` (12 matches) — Qlib integration has many placeholders.
- `report_gate.py` (4 matches) — Report gate has placeholder logic.
- Most are **documentation comments** or **TODO markers**, not active code paths.

---

## 8. `hardcoded` — 16 matches (6 production)

**Severity: 🟠 LOW** — Hardcoded values that should be configurable.

### Production Files (6)

| File | Count | Context |
|------|-------|---------|
| `scripts/audit_boundaries.py` | 7 | Audit boundaries has hardcoded paths |
| `Structural Deformation Research System/src/core/runtime_context.py` | 1 | Runtime context has hardcoded value |
| `Structural Deformation Research System/src/data/paths.py` | 1 | Data paths has hardcoded path |

### Test Files (10)

| File | Count | Context |
|------|-------|---------|
| `Structural Deformation Research System/tests/test_architecture_invariants.py` | 6 | Architecture invariant tests |
| `Structural Deformation Research System/tests/test_data_hub_lite.py` | 1 | Data hub lite tests |

### Risk Assessment

- `audit_boundaries.py` (7 matches) — audit script has hardcoded paths (acceptable for a script).
- `runtime_context.py` and `paths.py` — 1 each, minor.

---

## Severity Summary

| Severity | Pattern | Count | Action Required |
|----------|---------|-------|-----------------|
| 🔴 HIGH | `awaiting_data` | 19 production | Fill data gaps or remove dead code |
| 🔴 HIGH | `not_implemented` | 74 production | Implement or remove stubs |
| 🟡 MEDIUM | `diagnostic_only` | 29 production | Review if still needed |
| 🟡 MEDIUM | `fallback` | 102 production | Audit fallback chains for silent failures |
| 🟡 MEDIUM | `return None` | 241 production | Audit for silent failures vs legitimate optionals |
| 🟡 MEDIUM | `return {}` | 33 production | Audit for silent failures vs legitimate optionals |
| 🟠 LOW | `placeholder` | 23 production | Clean up TODOs |
| 🟠 LOW | `hardcoded` | 6 production | Minor, mostly scripts |

---

## Recommended Actions

1. **P0**: Address 19 `awaiting_data` in `structural_replay_v2.py` — either fetch the data or remove the dead event windows.
2. **P0**: Address 74 `not_implemented` in production — implement the critical ones (`pipeline.py`, `data_sources.py`) or mark as PAPER.
3. **P1**: Audit 102 `fallback` in `data_sources.py` (61) — ensure fallbacks don't mask data quality issues.
4. **P1**: Audit 241 `return None` — distinguish between legitimate optionals and silent failures.
5. **P2**: Clean up 23 `placeholder` comments and 6 `hardcoded` values.
