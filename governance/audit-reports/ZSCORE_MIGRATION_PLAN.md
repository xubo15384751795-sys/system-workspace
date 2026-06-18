# Z-Score Migration Plan

**Date:** 2026-06-03
**Status:** PLAN — comparison mode only

---

## Migration Phases

### Phase 1: Comparison mode ✅ DONE
- Define canonical_zscore_v1 spec
- Inventory all 12 implementations
- Compare on FRED:NFCI sample
- Result: replay_v2 ≈ canonical_v1 (r=0.995)

### Phase 2: Wire canonical_zscore_v1 into replay (PENDING)
- Add canonical_zscore_v1 as function in structural_replay_v2.py
- Add flag `use_canonical_zscore=False` to _freq_aware_zscore
- When flag=True, use canonical_zscore_v1 instead of _rolling_zscore
- Compare replay output with flag on/off
- **Precondition:** comparison shows |diff| < 0.1 for 95%+ of observations

### Phase 3: Switch replay to canonical_zscore_v1 (PENDING)
- Set `use_canonical_zscore=True` as default
- Run full 16-event replay
- Compare SigmaVector values
- **Precondition:** Phase 2 comparison passes

### Phase 4: Migrate proxy_builder (PENDING)
- Decision needed: keep 260w window or switch to 252d?
- Option A: canonical_zscore_v1 with 260w window (proxy_builder behavior preserved)
- Option B: canonical_zscore_v1 with 252d window (aligned with replay)
- **Precondition:** Elias decides window strategy

### Phase 5: Migrate other implementations (PENDING)
- Mark PAPER implementations as "pending migration to canonical_zscore_v1"
- Mark legacy implementations (bridge.py full-sample) as deprecated
- **Precondition:** Phase 3-4 complete

---

## Files to Modify (Phase 2 only)

| File | Change |
|------|--------|
| `scripts/structural_replay_v2.py` | Add canonical_zscore_v1 function; add flag to _freq_aware_zscore |
| `tests/governance/test_canonical_zscore.py` | NEW — test canonical_zscore_v1 properties |

## Files NOT Modified (until Phase 3+)

| File | Status |
|------|--------|
| `proxy_builder.py` | Pending — window decision needed |
| `data_sources.py` | Pending — legacy data layer |
| `gateway/bridge.py` | Pending — deprecated |
| `compute_proxies.py` | ARCHIVED — moved to `scripts/archive/`; standalone script |
| All PAPER implementations | Pending — no active consumer |

---

## Decision Needed

**proxy_builder window strategy:**
- Option A: Keep 260w (5-year normalization baseline) — more conservative
- Option B: Switch to 252d (1-year) — aligned with replay, more responsive

**Recommendation:** Option A (keep 260w) — proxy_builder serves a different purpose (Deformation run) than replay (historical event analysis). Different windows are acceptable if both are causal and winsorized.
