# K Data Upgrade Report

**Date:** 2026-06-03
**Sprint:** K Data Upgrade

---

## Current K State

| Sub-basket | Proxy | Raw Series | Status |
|------------|-------|-----------|--------|
| u1 iv_distortion | K_vix_term_structure_twist | CBOE:VIX9D, VIX3M, VIX6M | canonical_voting |
| u1 iv_distortion | K_u1_iv_term_twist_candidate | CBOE:VIX9D, VIX3M, VIX6M | candidate_pending_promotion |
| u2 jump_intensity | K_canonical_NOT_IMPLEMENTED_u2 | (none) | awaiting_data |
| u3 tail_convexity | K_cboe_skew_tail | CBOE:SKEW | canonical_voting |
| u3 tail_convexity | K_vvix_vol_of_vol | CBOE:VVIX | canonical_voting (auxiliary) |
| u3 tail_convexity | K_u3_tail_convexity_candidate | CBOE:SKEW | candidate_pending_promotion |
| u4 transition_instability | (none) | (none) | no proxy defined |

**Coverage:** u1 ✅, u2 ❌, u3 ✅, u4 ❌

---

## Available But Not Connected

| Series | Currently used by | K sub-basket | Can connect? |
|--------|------------------|-------------|-------------|
| CBOE:SPX | Not used in K | u2 jump_intensity | ✅ YES — daily returns → realized vol / jump proxy |
| CBOE:MOVE | Not used | u4 transition_instability | ✅ YES — rates vol instability |
| CBOE:TYVIX | Not used | u4 transition_instability | ✅ YES — Treasury vol |
| CBOE:VXTLT | Not used | u4 transition_instability | ✅ YES — TLT vol (cross-asset) |
| DERIVED:VIX3M_VIX_SLOPE | Not used in K | u1 iv_distortion | ✅ YES — term structure slope |

---

## Missing Data (Cannot Connect)

| Data | K sub-basket | Why needed |
|------|-------------|-----------|
| SPX options chain (OTM puts 5Δ-15Δ) | u3 tail_convexity | OTM put richness, crash skew |
| GEX (gamma exposure) | u3 tail_convexity | Dealer gamma stress |
| Intraday SPX (5-min returns) | u2 jump_intensity | Bipower variation, realized jumps |
| Cross-asset daily returns (TLT, HYG, EEM) | u4 transition_instability | Covariance eigenvector rotation |

---

## K Quality Assessment

| Metric | Current | After connecting available |
|--------|---------|--------------------------|
| Sub-baskets with data | 2/4 (u1, u3) | 4/4 (u1, u2, u3, u4) |
| Voting proxies | 3 | 6-8 |
| Data source diversity | CBOE only | CBOE + DERIVED |
| Temporal precision | daily | daily |
| §4.4 compliance | ✅ all options-derived | ✅ maintained |

---

## Recommendation

**Connect 5 available series to K sub-baskets:**

1. **CBOE:SPX → u2 jump_intensity** — daily returns as realized vol proxy
2. **CBOE:MOVE → u4 transition_instability** — rates vol instability
3. **CBOE:TYVIX → u4 transition_instability** — Treasury vol
4. **CBOE:VXTLT → u4 transition_instability** — TLT vol (cross-asset)
5. **DERIVED:VIX3M_VIX_SLOPE → u1 iv_distortion** — term structure slope

**Not recommended now:**
- Options chain data (requires new Harvester provider)
- GEX data (requires new data source)
- Intraday SPX (requires new data frequency)
- Cross-asset returns (requires new series)

**After this upgrade:** K would have 4/4 sub-baskets active with 6-8 voting proxies, all §4.4 compliant (options-derived).
