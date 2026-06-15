# Module Liveness Audit

**Generated:** 2026-06-02

---

## Summary

| Status | Count | Modules |
|--------|-------|---------|
| **ACTIVE** | 4 | Deformation Core, Harvester, Workbench Core, Workspace Scripts |
| **PARTIAL** | 2 | Workbench NLP, Workbench ML |
| **PAPER** | 2 | Learning Hub, Agent Harness |
| **STALE** | 1 | Deformation UI/Output (linked to old run) |
| **UNKNOWN** | 1 | Research Terminal |

---

## Detailed Assessment

### Deformation Core — ACTIVE

| Component | LOC | Tests | Status | Evidence |
|-----------|-----|-------|--------|----------|
| src/core | 2,608 | 12 | ACTIVE | models.py, interfaces.py — used by all other modules |
| src/derivation | 1,117 | 8 | ACTIVE | singular_detector.py, proxy_builder.py — core computation |
| src/proxies | 384 | 2 | ACTIVE | M/D/K/X proxy definitions — used by replay |
| src/dynamic | 2,107 | 15 | ACTIVE | trajectory, criticality, mismatch — used by replay |
| src/operators | 1,577 | 10 | ACTIVE | operator algebra — used by detector |
| src/diagnostics | 389 | 1 | ACTIVE | residualization — used by replay |
| src/validation | 300 | 2 | ACTIVE | walk_forward — used by backtests |
| src/research | 1,717 | 5 | ACTIVE | hypothesis, mechanisms — used by replay |
| src/output | 1,228 | 6 | **STALE** | output_exporter.py — last Deformation run 2026-04-22 |
| src/ui | 3,620 | 3 | **STALE** | Streamlit UI — not actively used |
| src/runtime | 1,558 | 4 | ACTIVE | assembly.py — used by Deformation runs |
| src/data | 7,455 | 12 | ACTIVE | gateway, sources — used by Harvester bridge |
| src/ml | 1,069 | 4 | **PAPER** | anomaly, reflexivity — no real model trained |

### Harvester — ACTIVE

| Component | LOC | Tests | Status | Evidence |
|-----------|-----|-------|--------|----------|
| providers/ | 2,400 | 10 | ACTIVE | FRED, CBOE, H41, SEC, Treasury — real API calls |
| core/ | 1,200 | 4 | ACTIVE | exporter, provenance, catalog — produces releases |
| quality/ | 600 | 2 | ACTIVE | checks, report — validates data |
| audit/ | 400 | 1 | ACTIVE | index — tracks data lineage |
| cli.py | 200 | 0 | ACTIVE | `python -m harvester` entry point |

### Workbench Core — ACTIVE

| Component | LOC | Tests | Status | Evidence |
|-----------|-----|-------|--------|----------|
| current.py | 1,800 | 15 | ACTIVE | `./sys check` — produces framework_output |
| evidence_dashboard.py | 800 | 8 | ACTIVE | `./sys evidence` — produces dashboard |
| freshness.py | 600 | 10 | ACTIVE | freshness manifest — validates data recency |
| governance/ | 1,500 | 12 | ACTIVE | semantic, authority, routing — enforces contracts |
| contract_validator.py | 400 | 6 | ACTIVE | validates workbench contracts |

### Workbench NLP — PAPER

| Component | LOC | Tests | Status | Evidence |
|-----------|-----|-------|--------|----------|
| extraction/ | 1,200 | 5 | PAPER | LLM extractor, entity/event/relation extractors — no corpus data |
| embeddings/ | 600 | 2 | PAPER | vector store, semantic search — no embeddings generated |
| chunking/ | 400 | 2 | PAPER | chunker, manifest — no documents chunked |
| cases/ | 500 | 2 | PAPER | case registry, similarity — no cases registered |
| candidate_ledger.py | 300 | 1 | PAPER | ledger — no entries |

### Workbench ML — PAPER

| Component | LOC | Tests | Status | Evidence |
|-----------|-----|-------|--------|----------|
| regime_detector.py | 400 | 2 | PAPER | no real model trained |
| factor_model.py | 300 | 1 | PAPER | no factors computed |
| graph_embed.py | 500 | 10 | PAPER | tests pass but no real graph embedded |
| gluonts_regime_forecaster.py | 200 | 1 | PAPER | uses seasonal naive backend |

### Learning Hub — PAPER

| Component | LOC | Tests | Status | Evidence |
|-----------|-----|-------|--------|----------|
| runtime/ | 800 | 2 | PAPER | pipeline, context, record — no runtime events |
| ledger/ | 600 | 1 | PAPER | store, query, append — no entries |
| analyzers/ | 700 | 0 | PAPER | recurrence, derive, governance_pressure — not run |
| governance/ | 500 | 1 | PAPER | lifecycle, verify — not exercised |
| cartography/ | 800 | 0 | PAPER | scanner, drift_detector — not run |

### Agent Harness — PAPER

| Component | LOC | Tests | Status | Evidence |
|-----------|-----|-------|--------|----------|
| entrypoints/ | 400 | 0 | PAPER | 4 CLI entrypoints — no agent session run |
| tools/ | 800 | 0 | PAPER | deformation, harvester, workbench, learning_hub tools — not exercised |
| hooks/ | 300 | 0 | PAPER | pre/post tool hooks — not triggered |
| workflows/ | 200 | 0 | PAPER | verify_only — not run |

### Workspace Scripts — ACTIVE

| Component | Status | Evidence |
|-----------|--------|----------|
| structural_replay_v2.py | ACTIVE | Produces 4-channel sigma_vector with 16 events |
| bridge_replay_to_current.py | ACTIVE | Produces framework_output.json |
| refresh_output_current.py | **STALE** | Links to 2026-04-22 run |
| build_benchmark_evidence_dashboard.py | ACTIVE | Produces evidence dashboard |
| compute_proxies.py | ACTIVE | Computes proxy values |
| Other scripts (~20) | UNKNOWN | Not checked individually |
