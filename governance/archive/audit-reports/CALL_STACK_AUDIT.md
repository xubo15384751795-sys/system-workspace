# Call Stack Audit — 11-Layer Pipeline

Generated: 2026-06-03
Scope: Full pipeline from Harvester data fetch through `./sys check` terminal output

---

## Pipeline Overview

```
Harvester (FRED/CBOE/OpenBB)
    ↓
Benchmark Panel (256K rows, 42 series)
    ↓
structural_replay_v2.py (4-channel, 16 events)
    ↓
bridge_replay_to_current.py → framework_output.json
    ↓
refresh_output_current.py → Output/current symlinks
    ↓
./sys check → terminal output
```

---

## Layer-by-Layer Audit

### Layer 1: Harvester Data Fetch

| Field | Value |
|-------|-------|
| **Input** | FRED API, CBOE API, OpenBB, SEC EDGAR |
| **Output** | Parquet files in `deformation-framework/data/` |
| **Downstream** | `harvester/derived.py` → benchmark panel |
| **empty_risk** | LOW — harvester has retry logic, 8+ providers in `structural-risk-harvester/src/harvester/providers/` |
| **schema_risk** | LOW — contracts in `harvester/providers/base.py` |
| **real_status** | **REAL** — 256K rows, 42 series fetched |
| **Key files** | `structural-risk-harvester/src/harvester/official.py`, `harvester/providers/fred.py`, `harvester/providers/cboe_direct.py`, `harvester/providers/h41.py` |

### Layer 2: Benchmark Panel Construction

| Field | Value |
|-------|-------|
| **Input** | Raw parquet from Layer 1 |
| **Output** | `benchmark_panel.parquet` — 256K rows, 42 series |
| **Downstream** | Proxy computation, structural replay |
| **empty_risk** | LOW — 256K rows confirmed |
| **schema_risk** | LOW — tested in `tests/test_benchmark_panel.py` |
| **real_status** | **REAL** — 256K rows, 42 series |
| **Key files** | `deformation-framework/src/benchmarks/benchmark_panel.py`, `deformation-framework/scripts/fetch_full_benchmark_panel.py` |

### Layer 3: Proxy Computation (ProxyBuilder)

| Field | Value |
|-------|-------|
| **Input** | Benchmark panel parquet |
| **Output** | M, D, K, X proxy series |
| **Downstream** | SigmaVector, structural replay |
| **empty_risk** | MEDIUM — `X_PRE`/`X_REALIZED` return `None` (deprecated) |
| **schema_risk** | MEDIUM — `MEASUREMENT_CHANNELS` includes deprecated channels |
| **real_status** | **PARTIAL** — M/D/K/X work, X_PRE/X_REALIZED don't |
| **Key files** | `deformation-framework/src/derivation/proxy_builder.py` (`ProxyBuilder.build_proxies()`) |
| **Deprecation** | `X_PRE`, `X_REALIZED` in `proxy_builder.py` lines referencing `singular_detector.py` |

### Layer 4: SigmaVector Construction

| Field | Value |
|-------|-------|
| **Input** | M, D, K, X proxy series |
| **Output** | `sigma_vector.json` — 4-channel dict |
| **Downstream** | Structural replay, framework output |
| **empty_risk** | HIGH — old Deformation run produced `{}` (empty dict) |
| **schema_risk** | HIGH — two competing implementations (see REDUNDANCY_AUDIT.md) |
| **real_status** | **REAL** in `structural_replay_v2.py` (16 events, 4-channel); **BROKEN** in old Deformation run path |
| **Key files** | `deformation-framework/src/derivation/singular_detector.py` (class `SigmaVector`), `Workbench/src/workbench/governance/semantic.py` (dict-based SigmaVector) |

### Layer 5: Structural Replay v2

| Field | Value |
|-------|-------|
| **Input** | Benchmark panel + SigmaVector |
| **Output** | `Output/sandbox/structural_replay_v2/sigma_vector.json` — 4-channel, 16 events |
| **Downstream** | Bridge replay to current |
| **empty_risk** | LOW — 16 events confirmed |
| **schema_risk** | LOW — validated in `tests/test_sigma_vector.py` |
| **real_status** | **REAL** — 4-channel, 16 events |
| **Key files** | `scripts/structural_replay_v2.py` |
| **Evidence** | `Output/sandbox/structural_replay_v2/results.json`, 16 event window CSVs in `event_windows/` |

### Layer 6: Bridge Replay to Current

| Field | Value |
|-------|-------|
| **Input** | Structural replay sigma_vector.json |
| **Output** | `Output/current/framework_output.json` — `ACTIVE_FULL` status |
| **Downstream** | refresh_output_current.py |
| **empty_risk** | LOW — bridge is the active path |
| **schema_risk** | MEDIUM — 7 files write framework_output (see REDUNDANCY_AUDIT.md) |
| **real_status** | **REAL** — `ACTIVE_FULL` confirmed |
| **Key files** | `scripts/bridge_replay_to_current.py` |

### Layer 7: refresh_output_current.py

| Field | Value |
|-------|-------|
| **Input** | Latest Deformation run + bridge output |
| **Output** | `Output/current/` symlinks and files |
| **Downstream** | `./sys check` |
| **empty_risk** | MEDIUM — links to stale Deformation run (2026-04-26), bypassed by bridge |
| **schema_risk** | LOW — symlink management only |
| **real_status** | **PARTIAL** — links to stale run, bridge fixes this |
| **Key files** | `scripts/refresh_output_current.py` |

### Layer 8: framework_output.json Persistence

| Field | Value |
|-------|-------|
| **Input** | Bridge output or Deformation run |
| **Output** | `Output/current/framework_output.json` |
| **Downstream** | `00_READ_ME_FIRST.md` generation |
| **empty_risk** | MEDIUM — old path produces empty/stale data |
| **schema_risk** | HIGH — 7 divergent writers (see REDUNDANCY_AUDIT.md) |
| **real_status** | **PARTIAL** — bridge fixes, old path broken |
| **Key files** | `scripts/bridge_replay_to_current.py`, `Workbench/src/workbench/current.py`, `scripts/refresh_output_current.py` |

### Layer 9: 00_READ_ME_FIRST.md Generation

| Field | Value |
|-------|-------|
| **Input** | `framework_output.json` |
| **Output** | `Output/current/00_READ_ME_FIRST.md` |
| **Downstream** | `./sys check` display |
| **empty_risk** | LOW — file exists |
| **schema_risk** | LOW — template-based |
| **real_status** | **REAL** |
| **Key files** | `scripts/refresh_output_current.py`, `Workbench/src/workbench/workspace/system_status.py` |

### Layer 10: `./sys check` Command

| Field | Value |
|-------|-------|
| **Input** | `Output/current/00_READ_ME_FIRST.md` |
| **Output** | First 55 lines to stdout |
| **Downstream** | Terminal display |
| **empty_risk** | LOW — file exists |
| **schema_risk** | NONE — display-only |
| **real_status** | **REAL** |
| **Key files** | `/Users/a1/System/sys` (bash, line 19: `sed -n '1,55p'`) |

### Layer 11: Terminal Display

| Field | Value |
|-------|-------|
| **Input** | stdout from `./sys check` |
| **Output** | Human-readable terminal output |
| **Downstream** | None (end of pipeline) |
| **empty_risk** | NONE |
| **schema_risk** | NONE |
| **real_status** | **REAL** |

---

## Status Summary

| Layer | Component | Status |
|-------|-----------|--------|
| 1 | Harvester Data Fetch | ✅ REAL |
| 2 | Benchmark Panel | ✅ REAL |
| 3 | ProxyBuilder | ⚠️ PARTIAL (X_PRE/X_REALIZED broken) |
| 4 | SigmaVector | ⚠️ PARTIAL (old path BROKEN, new path REAL) |
| 5 | Structural Replay v2 | ✅ REAL |
| 6 | Bridge Replay to Current | ✅ REAL |
| 7 | refresh_output_current.py | ⚠️ PARTIAL (stale links) |
| 8 | framework_output.json | ⚠️ PARTIAL (divergent writers) |
| 9 | 00_READ_ME_FIRST.md | ✅ REAL |
| 10 | `./sys check` | ✅ REAL |
| 11 | Terminal Display | ✅ REAL |

### Additional Paths (Not in Main Pipeline)

| Component | Status | Notes |
|-----------|--------|-------|
| NLP Pipeline | 📄 PAPER | Code exists in `Workbench/src/nlp/`, no data flows |
| Learning Hub | 📄 PAPER | 1 git commit, no runtime events |
| Backtest Lens | 📄 PAPER | Code exists, not wired to pipeline |
| Research Terminal | ❓ UNKNOWN | Not checked in this audit |

---

## Broken/Paper/Partial Details

### BROKEN: Deformation Run SigmaVector Persistence

- **File**: `deformation-framework/src/derivation/singular_detector.py`
- **Function**: `SigmaVector` class persistence
- **Issue**: Old Deformation run writes `{}` to `sigma_vector.json`
- **Fix**: Bridge (`scripts/bridge_replay_to_current.py`) overwrites with real data

### PARTIAL: ProxyBuilder X_PRE/X_REALIZED

- **File**: `deformation-framework/src/derivation/proxy_builder.py`
- **Function**: `ProxyBuilder.build_proxies()`
- **Issue**: `X_PRE` and `X_REALIZED` return `None` (deprecated)
- **Impact**: All channels show `PROXY_REDUCED distance=3`

### PARTIAL: refresh_output_current.py Stale Links

- **File**: `scripts/refresh_output_current.py`
- **Issue**: Links to Deformation run dated 2026-04-26
- **Fix**: Bridge script bypasses this by writing directly to `Output/current/`

### PAPER: NLP Pipeline

- **Files**: `Workbench/src/nlp/extraction/llm_extractor.py`, `Workbench/src/nlp/extraction/table_extractor.py`, `Workbench/src/nlp/extraction/relation_extractor.py`
- **Issue**: Code exists but no data flows through the pipeline

### PAPER: Learning Hub

- **Files**: `system-learning-hub/src/system_learning/runtime/pipeline.py`, `system-learning-hub/src/system_learning/runtime/record.py`
- **Issue**: 1 git commit, no runtime events recorded
