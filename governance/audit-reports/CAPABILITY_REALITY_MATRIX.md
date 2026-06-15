# Capability Reality Matrix

**Generated:** 2026-06-02
**Method:** Code trace + artifact verification + test execution

---

## Legend

| Status | Meaning |
|--------|---------|
| **REAL** | Code runs, produces real output, consumed downstream, tested |
| **PARTIAL** | Code runs but has gaps (empty objects, stale data, missing coverage) |
| **PAPER** | Code exists, tests pass, but no real data flows through |
| **FAKE** | Output is mock/placeholder disguised as real capability |
| **UNKNOWN** | Cannot determine from available evidence |

---

## Capability Assessment

| # | Capability | Status | Evidence |
|---|-----------|--------|----------|
| 1 | **Data Freshness** | **REAL** | Harvester fetches live FRED/CBOE/H41/SEC data. benchmark_panel.parquet has 256K rows, 42 series, vintage_date=2026-06-02. `./sys evidence` shows freshness counts. |
| 2 | **Source Health** | **PARTIAL** | freshness_manifest.json exists and shows fresh/stale/missing counts. But source health interpretation is code-generated from freshness data, not from actual source health monitoring. No alerting on source failure. |
| 3 | **Proxy Builder** | **PARTIAL** | `DefaultProxyBuilder.build()` in `proxy_builder.py` computes M/D/K/X from real data. But MEASUREMENT_CHANNELS still includes deprecated X_PRE/X_REALIZED. In last Deformation run (2026-04-22), X_PRE=None, X_REALIZED=None. X_agg not computed by ProxyBuilder (computed by replay instead). |
| 4 | **M/D/K/X_agg Voting** | **REAL** | structural_replay_v2.py PROXY_REGISTRY has canonical_voting proxies for all 4 channels. SigmaVector shows M=-0.75, D=-0.88, K=-1.19, X_agg=-0.76. cofire_count=4. `test_canonical_proxy_alignment.py` enforces voting rules. |
| 5 | **Structural Replay** | **REAL** | `scripts/structural_replay_v2.py` processes 16 historical events with 4-channel analysis. Output: sigma_vector.json + results.json + evaluation_report.md. Events include Asian 1997 through August 2024. |
| 6 | **Historical Event Replay** | **REAL** | 16 events with per-event channel_at_peak values. X_agg fires in 11/16 events, dominant in 5. Correlation matrix computed. See HISTORICAL_EVENT_REPLAY_4CH_REPORT.md. |
| 7 | **Measurement Blind Spot Detection** | **REAL** | When channels are NOT_IMPLEMENTED, system correctly reports "Measurement Blind Spot". Now that 4/4 are live, blind spot is NO. Detection logic in `structural_replay_v2.py` event analysis. |
| 8 | **Governance Contract Enforcement** | **REAL** | `test_canonical_proxy_alignment.py` has 11 tests enforcing: canonical channels, sub-basket coverage, forbidden groups, K options-derived, X_PRE/X_REALIZED not voting. `test_semantic_registry.py` validates SigmaVector. Anti-gaming tests prevent fake metrics. |
| 9 | **Framework Output Persistence** | **PARTIAL** | bridge_replay_to_current.py produces framework_output.json with ACTIVE_FULL. But the Deformation run path (`refresh_output_current.py`) still links to stale 2026-04-22 run with empty SigmaVector. Bridge is a workaround, not a fix. |
| 10 | **Dashboard/Report** | **PARTIAL** | `./sys evidence` generates benchmark_evidence_dashboard.md with real data. `./sys check` shows ACTIVE_FULL. But `./sys open` links to stale Deformation report (2026-04-26). latest_report.html is 4235 bytes — minimal, not a rich dashboard. |
| 11 | **Backtest Lens** | **PAPER** | `scripts/run_historical_replay.py` and `scripts/run_allocation_backtest.py` exist with `if __name__ == '__main__'`. But they are not wired to any output path. No artifacts produced. No downstream consumer. |
| 12 | **NLP Pipeline** | **PAPER** | `Workbench/src/nlp/` has 48 Python files, 4882 LOC, 203 functions, 42 classes. Tests pass. But no corpus data flows through. `candidate_ledger.py` has no entries. `nlp_extract.py` and `nlp_ingest.py` scripts exist but have no data source. |
| 13 | **Research Terminal** | **UNKNOWN** | `research_terminal/cli.py` exists. Not checked for functionality. |
| 14 | **Agent Harness** | **PAPER** | `Workbench/agents/harness/` has entrypoints, tools, hooks. But no agent session has been run through it. Tools reference Deformation/Harvester/Learning Hub APIs but no real agent workflow has been executed. |
| 15 | **Learning Hub** | **PAPER** | `system-learning-hub/` has 42 Python files, 4112 LOC. Only 1 git commit. No runtime events generated. `improvement_queue.md` not produced. `system_health_report.md` not produced. |
| 16 | **ML Signals** | **PAPER** | `Workbench/src/ml/` has regime_detector, factor_model, graph_embed, gluonts_regime_forecaster. Tests pass. But no real model has been trained or served. No signal artifacts produced. |
| 17 | **Qlib Benchmark** | **PAPER** | `ExternalTools/qlib_benchmark_runner/` exists with runner code. But Qlib is not installed. `run_qlib_benchmark.py` has placeholder metrics fallback. |
| 18 | **OpenBB Integration** | **PARTIAL** | `openbb_secondary_audit.py` exists. Data Hub uses OpenBB for some series. But OpenBB is used as a secondary audit path, not primary data source. |

---

## Summary

| Status | Count | Capabilities |
|--------|-------|-------------|
| **REAL** | 6 | Data Freshness, M/D/K/X_agg Voting, Structural Replay, Historical Event Replay, Blind Spot Detection, Governance Enforcement |
| **PARTIAL** | 5 | Source Health, Proxy Builder, Framework Output, Dashboard/Report, OpenBB |
| **PAPER** | 6 | Backtest Lens, NLP Pipeline, Agent Harness, Learning Hub, ML Signals, Qlib Benchmark |
| **UNKNOWN** | 1 | Research Terminal |

**The system has 6 REAL capabilities and 6 PAPER capabilities.** The REAL capabilities form a coherent chain: Harvester → Replay → SigmaVector → framework_output → ./sys check. The PAPER capabilities are code that exists and tests pass, but no real data flows through them.
