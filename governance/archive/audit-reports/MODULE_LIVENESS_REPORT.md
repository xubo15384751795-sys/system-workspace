# Module Liveness Report

**Generated:** 2026-06-02
**Scope:** All 5 System repos + workspace scripts
**Auditor:** Hermes Agent (module-liveness-auditor)

---

## Summary

| Module | Files | LOC | Tests | Classes | Functions | Status |
|--------|-------|-----|-------|---------|-----------|--------|
| Deformation Framework | 215 | 31,034 | 63 | 294 | 1,391 | 🟢 Active |
| Workbench | 102 | 14,311 | 11 | 62 | 559 | 🟢 Active |
| Harvester | 27 | 5,728 | 17 | 31 | 197 | 🟢 Active |
| Learning Hub | 42 | 4,112 | 5 | 17 | 169 | 🟡 Active but thin |
| Workspace Scripts | 32 | ~3,500 | 0 | — | — | 🟢 Active |
| Workspace Tests | 35 | ~2,000 | 35 | — | — | 🟢 Active |
| External Tools | 8 | ~800 | 1 | — | — | 🟡 Minimal |

**Total:** 638 Python files, ~52K LOC, 132 test files

---

## Deformation Framework — 🟢 ACTIVE

**31,034 LOC across 13 submodules, 63 test files**

| Submodule | LOC | Funcs | Classes | Status |
|-----------|-----|-------|---------|--------|
| core | 2,608 | 141 | 62 | 🟢 Implemented (models, interfaces, state) |
| derivation | 1,117 | 49 | 7 | 🟢 Implemented (singular detector, proxy builder, belief) |
| dynamic | 2,107 | 81 | 15 | 🟢 Implemented (trajectory, criticality, mismatch, transition) |
| operators | 1,577 | 79 | 10 | 🟢 Implemented (operator algebra, diagnostics, registry) |
| proxies | 384 | 4 | 3 | 🟢 Implemented (M/D/K/X proxy definitions) |
| diagnostics | 389 | 17 | 1 | 🟢 Implemented |
| validation | 300 | 18 | 2 | 🟢 Implemented (walk-forward) |
| ml | 1,069 | 54 | 11 | 🟢 Implemented (GluonTS, anomaly, reflexivity) |
| research | 1,717 | 62 | 29 | 🟢 Implemented (hypothesis, mechanisms, scenarios) |
| output | 1,228 | 46 | 0 | 🟢 Implemented (run package, exporter) |
| ui | 3,620 | 137 | 3 | 🟢 Implemented (components, helpers, charts) |
| runtime | 1,558 | 83 | 8 | 🟢 Implemented (assembly, config, session) |
| data | 7,455 | 327 | 78 | 🟢 Implemented (gateway, sources, adapters) |

**Skeleton functions found:** 8 (all in ui/helpers or core/representation — non-critical)
- `ui/helpers/ui_runtime.py`: `write_event`, `load_events` (ellipsis-only)
- `core/representation/`: `graph_repr`, `topology_stub`, `state_space_mapping` (ellipsis-only — these are intentional stubs for future graph representation)

**Docstring coverage:** 136/1,391 functions (10%) — low but typical for research code

---

## Workbench — 🟢 ACTIVE

**14,311 LOC across 4 submodules, 11 test files**

| Submodule | LOC | Funcs | Classes | Status |
|-----------|-----|-------|---------|--------|
| workbench | 6,529 | 267 | 16 | 🟢 Implemented (current, evidence, governance, NLP, contracts) |
| nlp | 4,882 | 203 | 42 | 🟢 Implemented (extraction, embeddings, chunking, cases, narrative) |
| ml | 1,834 | 58 | 4 | 🟢 Implemented (regime detection, factor model, GluonTS) |
| benchmarks | 1,066 | 31 | 0 | 🟢 Implemented (market feedback, Qlib runner) |

**Skeleton functions:** 4 (all exception classes — pass-only, which is correct)
- `contract_validator.py`: `ValidationError`
- `report_gate.py`: `ReportGateError`
- `routing_gate.py`: `RoutingGateError`
- `ml_signal_writer.py`: `MLSignalWriteError`

**Docstring coverage:** 101/559 functions (18%) — best of all modules

---

## Harvester — 🟢 ACTIVE

**5,728 LOC, 17 test files**

| Component | Status |
|-----------|--------|
| Providers (FRED, H.4.1, SEC, Treasury, CBOE, OpenBB) | 🟢 Implemented |
| Core (exporter, provenance, catalog, manifest) | 🟢 Implemented |
| Quality (checks, report) | 🟢 Implemented |
| Audit (index) | 🟢 Implemented |
| CLI | 🟢 Implemented |

**Skeleton:** 1 (`providers/base.py::fetch_series` — abstract base, intentional)

**Docstring coverage:** 28/197 functions (14%)

---

## Learning Hub — 🟡 ACTIVE BUT THIN

**4,112 LOC, only 5 test files**

| Component | LOC | Status |
|-----------|-----|--------|
| runtime (pipeline, context, record) | ~800 | 🟢 Implemented |
| ledger (store, query, append) | ~600 | 🟢 Implemented |
| analyzers (recurrence, derive, governance_pressure) | ~700 | 🟢 Implemented |
| governance (lifecycle, verify) | ~500 | 🟢 Implemented |
| cartography (scanner, drift_detector, import_graph) | ~800 | 🟢 Implemented |
| ml_integrity (pollution_monitor, constitution) | ~400 | 🟢 Implemented |
| schema, reports, ingestion | ~300 | 🟢 Implemented |

**Concern:** Only 5 test files for 4,112 LOC and 169 functions. The test-to-code ratio is the weakest of all modules. The git log shows only 1 commit for system-learning-hub — this module may have been bulk-imported and not iteratively developed.

**No skeleton functions found** — but low test coverage means confidence is limited.

---

## Workspace Scripts — 🟢 ACTIVE

**32 files, governance test suite in tests/governance/**

Key scripts:
- `structural_replay_v2.py` — Main replay engine (canonical proxy registry)
- `compute_proxies.py` — ARCHIVED (moved to `scripts/archive/`); proxy computation now via `structural_replay_v2.py`
- `wiki_system_bridge_audit.py` — Wiki-to-system audit
- `system_status.py`, `list_latest.py`, `build_system_index.py` — Workspace utilities

Governance tests (in `tests/governance/`):
- `test_canonical_proxy_alignment.py` — 8 tests enforcing proxy spec
- `test_semantic_registry.py` — Sigma vector tests
- `test_routing_gate_blocks_promotion.py` — Routing gate tests
- `anti_gaming/` — 4 anti-gaming tests

---

## External Tools — 🟡 MINIMAL

- `ExternalTools/qlib_benchmark_runner/` — Qlib subprocess runner
- 8 files, ~800 LOC, 1 test
- Correctly isolated (sandbox boundary)

---

## Documentation Coverage

| Module | Functions | With Docstrings | Coverage |
|--------|-----------|-----------------|----------|
| Deformation | 1,391 | 136 | 10% |
| Workbench | 559 | 101 | 18% |
| Harvester | 197 | 28 | 14% |
| Learning Hub | 169 | 22 | 13% |

---

## Recommendations

1. **Learning Hub needs more tests** — 5 tests for 4,112 LOC is a risk. Priority: governance lifecycle, ledger append/query, pollution monitor.
2. **Deformation core/representation stubs** — `graph_repr.py`, `topology_stub.py`, `state_space_mapping.py` have ellipsis-only methods. Either implement or mark as `@abstractmethod`.
3. **Docstring coverage is uniformly low** — Not blocking, but for a system with semantic distance tracking, the lack of docstrings makes it harder to verify that code intent matches spec intent.
4. **No dead modules found** — All submodules have real code. No orphan modules detected.
