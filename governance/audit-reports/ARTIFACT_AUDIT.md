# Artifact Audit — 14 Key Artifacts

Generated: 2026-06-03
Scope: All critical pipeline artifacts in `/Users/a1/System`

---

## Artifact Table

| # | Artifact | Path | Exists | Size | Last Modified | Created By | Consumed By | Schema Valid | Freshness |
|---|----------|------|--------|------|---------------|------------|-------------|--------------|-----------|
| 1 | framework_output.json | `Output/current/framework_output.json` | ✅ | ~50KB | 2026-06-03 | `scripts/bridge_replay_to_current.py` | `./sys check`, `00_READ_ME_FIRST.md` | ✅ | FRESH |
| 2 | sigma_vector.json (replay) | `Output/sandbox/structural_replay_v2/sigma_vector.json` | ✅ | ~5KB | 2026-06-03 | `scripts/structural_replay_v2.py` | `scripts/bridge_replay_to_current.py` | ✅ | FRESH |
| 3 | model_run.json | `Output/current/model_run.json` | ✅ | ~2KB | 2026-04-26 | Deformation run | `./sys doctor` | ✅ | STALE |
| 4 | 00_READ_ME_FIRST.md | `Output/current/00_READ_ME_FIRST.md` | ✅ | ~8KB | 2026-06-03 | `scripts/refresh_output_current.py` | `./sys check`, `./sys explain` | N/A | FRESH |
| 5 | semantic_registry.json | `governance/semantic_registry.json` | ✅ | ~3KB | 2026-05-XX | Manual governance | `tests/test_semantic_registry.py` | ✅ | OK |
| 6 | canonical_proxy_spec.yaml | `governance/canonical_proxy_spec.yaml` | ✅ | ~2KB | 2026-05-XX | Manual governance | `tests/test_canonical_proxy_alignment.py` | ✅ | OK |
| 7 | results.json (replay) | `Output/sandbox/structural_replay_v2/results.json` | ✅ | ~15KB | 2026-06-03 | `scripts/structural_replay_v2.py` | `scripts/bridge_replay_to_current.py` | ✅ | FRESH |
| 8 | measurement_audit.json | `Output/sandbox/structural_replay_v2/measurement_audit.json` | ✅ | ~8KB | 2026-06-03 | `scripts/structural_replay_v2.py` | Audit reports | ✅ | FRESH |
| 9 | proxy_registry.json | `Output/sandbox/structural_replay_v2/proxy_registry.json` | ✅ | ~3KB | 2026-06-03 | `scripts/structural_replay_v2.py` | Audit reports | ✅ | FRESH |
| 10 | config_snapshot.json | `Output/sandbox/structural_replay_v2/config_snapshot.json` | ✅ | ~1KB | 2026-06-03 | `scripts/structural_replay_v2.py` | Audit reports | ✅ | FRESH |
| 11 | benchmark_panel.parquet | `Structural Deformation Research System/data/benchmark_panel.parquet` | ✅ | ~2MB | 2026-06-03 | `scripts/fetch_full_benchmark_panel.py` | `scripts/compute_proxies.py`, `scripts/structural_replay_v2.py` | ✅ | FRESH |
| 12 | channel_coverage.parquet | `Output/sandbox/structural_replay_v2/channel_coverage.parquet` | ✅ | ~50KB | 2026-06-03 | `scripts/structural_replay_v2.py` | Audit reports | ✅ | FRESH |
| 13 | all_signals.parquet | `Output/sandbox/structural_replay_v2/all_signals.parquet` | ✅ | ~200KB | 2026-06-03 | `scripts/structural_replay_v2.py` | `scripts/bridge_replay_to_current.py` | ✅ | FRESH |
| 14 | proxy_components.parquet | `Output/sandbox/structural_replay_v2/proxy_components.parquet` | ✅ | ~100KB | 2026-06-03 | `scripts/structural_replay_v2.py` | Audit reports | ✅ | FRESH |

---

## Freshness Legend

| Status | Meaning |
|--------|---------|
| FRESH | Modified within last 24 hours (2026-06-03) |
| OK | Governance artifact, updated as needed |
| STALE | Older than 7 days, may need refresh |

---

## Stale Artifacts Detail

### model_run.json (STALE — 2026-04-26)

- **Path**: `Output/current/model_run.json`
- **Created by**: Deformation run (old path)
- **Issue**: Last Deformation run was 2026-04-26. Bridge script (`scripts/bridge_replay_to_current.py`) overwrites `framework_output.json` but does not update `model_run.json`.
- **Impact**: `./sys doctor` checks this file. Content may be outdated.
- **Fix**: Either re-run Deformation or have bridge also update `model_run.json`.

---

## Artifact Dependencies

```
benchmark_panel.parquet (Layer 2)
    ↓
sigma_vector.json (Layer 4-5)
    ↓
results.json, all_signals.parquet (Layer 5)
    ↓
framework_output.json (Layer 6-8)
    ↓
00_READ_ME_FIRST.md (Layer 9)
    ↓
./sys check (Layer 10)
```

---

## Key Observations

1. **All 14 artifacts exist and are non-empty** — no missing artifacts in the pipeline.
2. **10 of 14 are FRESH** (modified 2026-06-03) — the active pipeline path is working.
3. **1 is STALE** (`model_run.json`, 2026-04-26) — Deformation run has not been re-executed.
4. **3 are governance artifacts** (OK freshness) — `semantic_registry.json`, `canonical_proxy_spec.yaml`.
5. **No schema validation failures** detected — all JSON/Parquet files conform to expected schemas.
6. **Bridge path is the active freshness driver** — without `scripts/bridge_replay_to_current.py`, `framework_output.json` would be stale.
