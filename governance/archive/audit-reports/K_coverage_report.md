# K Channel MVP Coverage Report

**Generated:** 2026-06-02
**Panel:** `Data/harvester/exports/2026-06-02-r8/data/benchmark_panel.parquet`
**Status:** 0/20 proxy inputs wired (all AWAITING_DATA)

---

## Summary

The K channel (transition_deformation) defines 20 proxy inputs across 4 groups. The Harvester panel contains CBOE volatility surface series (VIX, VVIX, SKEW, VIX9D, VIX3M, VIX6M, MOVE, TYVIX, VXTLT) plus derived slope series. Several K proxy inputs can be directly connected or derived from these series. Others require intraday/options-level data not currently in the panel.

---

## Proxy Input → Raw Data Mapping

### Group: K_IV_SURFACE_DEFORMATION (6 inputs)

| proxy_input_id | raw_series_available | can_connect | priority | notes |
|---|---|---|---|---|
| K_IV_SURFACE_DEFORMATION | CBOE:SKEW, CBOE:VIX9D, CBOE:VIX3M, CBOE:VIX6M | ✅ YES | P1 | Composite — can be derived as weighted basket of other group members once they exist |
| K_IV_DISTORTION | (none direct) | ⚠️ PARTIAL | P2 | Needs full IV surface (strike × expiry). SKEW is a partial proxy. Requires options chain data |
| K_SKEW_SLOPE | CBOE:SKEW | ✅ YES | P1 | Direct: SKEW = CBOE skew index, measures 30-day OTM put/call skew |
| K_SMILE_CURVATURE | CBOE:SKEW (partial) | ⚠️ PARTIAL | P2 | SKEW captures skew but not full smile curvature (needs wing data) |
| K_TERM_STRUCTURE_TWIST | CBOE:VIX9D, CBOE:VIX3M, CBOE:VIX6M, DERIVED:VIX3M_VIX_SLOPE | ✅ YES | P1 | VIX term structure slope/twist directly computable from 9D/3M/6M |
| K_VARIANCE_RISK_PREMIUM_INSTABILITY | CBOE:VIX, FRED:VIXCLS, CBOE:SPX | ✅ YES | P1 | VRP = VIX² − realized variance (from SPX returns). Instability = rolling σ of VRP |

### Group: K_JUMP_DISCONTINUITY (4 inputs)

| proxy_input_id | raw_series_available | can_connect | priority | notes |
|---|---|---|---|---|
| K_JUMP_DISCONTINUITY | (none) | ❌ NO | P3 | Composite of realized jump + bipower gap — needs sub-members first |
| K_REALIZED_JUMP | CBOE:SPX (daily only) | ⚠️ PARTIAL | P2 | Daily returns can proxy jumps (abs return > 2σ). True jump intensity needs intraday |
| K_BIPOWER_GAP | (none) | ❌ NO | P3 | Bipower variation requires intraday 5-min returns. Not in panel |
| K_OVERNIGHT_GAP_FREQUENCY | CBOE:SPX | ⚠️ PARTIAL | P2 | Can approximate with daily open-vs-close gap if open price available. Panel has close only |

### Group: K_TAIL_CONVEXITY (5 inputs)

| proxy_input_id | raw_series_available | can_connect | priority | notes |
|---|---|---|---|---|
| K_TAIL_CONVEXITY | CBOE:VVIX, CBOE:SKEW | ⚠️ PARTIAL | P2 | Composite — can be partially derived once sub-members exist |
| K_OTM_PUT_RICHNESS | (none direct) | ❌ NO | P3 | Needs OTM put option prices (5Δ–15Δ). Not in panel |
| K_CRASH_SKEW | CBOE:SKEW | ✅ YES | P1 | SKEW index is explicitly designed as crash-risk / tail-skew measure |
| K_VVIX | CBOE:VVIX | ✅ YES | P1 | Direct match: VVIX = VIX-of-VIX, measures vol-of-vol convexity |
| K_GAMMA_STRESS | (none direct) | ❌ NO | P3 | Needs GEX (gamma exposure) data from options OI. Not in panel |

### Group: K_TRANSITION_INSTABILITY (5 inputs)

| proxy_input_id | raw_series_available | can_connect | priority | notes |
|---|---|---|---|---|
| K_TRANSITION_INSTABILITY | (none) | ❌ NO | P3 | Composite of sub-members |
| K_ROLLING_BETA_INSTABILITY | CBOE:SPX + cross-asset | ⚠️ PARTIAL | P2 | Derivable if cross-asset returns available (e.g., TLT, HYG). Panel has VXTLT as proxy |
| K_COVARIANCE_EIGENVECTOR_ROTATION | (multivariate returns needed) | ❌ NO | P3 | Needs full multivariate return matrix. Panel lacks cross-asset daily returns |
| K_CORRELATION_NETWORK_REWIRING | (multivariate returns needed) | ❌ NO | P3 | Same: needs rolling correlation matrix across assets |
| K_REGIME_SWITCHING_RESIDUAL | CBOE:SPX | ⚠️ PARTIAL | P2 | Can fit simple regime model on SPX; residuals proxy regime switching |

---

## Connectivity Summary

| Status | Count | Proxy Inputs |
|---|---|---|
| ✅ YES (direct / derivable) | **6** | K_IV_SURFACE_DEFORMATION, K_SKEW_SLOPE, K_TERM_STRUCTURE_TWIST, K_VARIANCE_RISK_PREMIUM_INSTABILITY, K_CRASH_SKEW, K_VVIX |
| ⚠️ PARTIAL (approximation possible) | **5** | K_IV_DISTORTION, K_SMILE_CURVATURE, K_REALIZED_JUMP, K_TAIL_CONVEXITY, K_ROLLING_BETA_INSTABILITY, K_REGIME_SWITCHING_RESIDUAL |
| ❌ NO (data missing) | **9** | K_JUMP_DISCONTINUITY, K_BIPOWER_GAP, K_OVERNIGHT_GAP_FREQUENCY, K_OTM_PUT_RICHNESS, K_GAMMA_STRESS, K_TRANSITION_INSTABILITY, K_COVARIANCE_EIGENVECTOR_ROTATION, K_CORRELATION_NETWORK_REWIRING |

> **Correction:** 6 YES + 6 PARTIAL + 8 NO = 20

---

## Existing Derived Series in Panel (K-relevant)

| series_id | rows | K-relevance |
|---|---|---|
| DERIVED:VIX3M_VIX_SLOPE | 4,199 | Direct input for K_TERM_STRUCTURE_TWIST |
| DERIVED:MOVE_PROXY | 9,197 | Rates vol (TYVIX/MOVE) — control benchmark, not K input |
| DERIVED:SPX_ROLL_SPREAD | 12,950 | Futures roll basis — not directly K |

---

## K StateVariable Status (from structural_replay_v2.py)

The K StateVariable (lines 366–417) documents:

- **canonical_status:** `drifted_pending_repair`
- **Allowed groups:** `iv_distortion`, `jump_intensity`, `tail_convexity` (+ legacy `credit_surface`, `convexity_surface`, `cross_asset_curvature`)
- **Forbidden groups:** `funding_spread`, `official_liquidity_facility`, `volatility_jump`, `rates_curve`
- **Key note:** "K aggregates to NaN today (no canonical_voting K proxy yet). u1 (term-structure twist) and u3 (SKEW tail convexity) are candidate_pending_promotion; u2 (jump intensity) still awaiting_data."

---

## What Is Still Needed (Harvester Shopping List)

### P1 — Can be built NOW from existing panel data

These 6 proxies require no new data acquisition:

1. **K_SKEW_SLOPE** ← `CBOE:SKEW`
2. **K_VVIX** ← `CBOE:VVIX`
3. **K_TERM_STRUCTURE_TWIST** ← `CBOE:VIX9D`, `CBOE:VIX3M`, `CBOE:VIX6M` (or `DERIVED:VIX3M_VIX_SLOPE`)
4. **K_VARIANCE_RISK_PREMIUM_INSTABILITY** ← `CBOE:VIX` + `CBOE:SPX` returns for realized variance
5. **K_CRASH_SKEW** ← `CBOE:SKEW`
6. **K_IV_SURFACE_DEFORMATION** ← composite of #1–#5

### P2 — Approximations possible, upgrades later

- **K_REALIZED_JUMP**: daily abs returns as proxy → need intraday SPX for true bipower
- **K_TAIL_CONVEXITY**: VVIX+SKEW partial → need OTM put prices for full tail convexity
- **K_ROLLING_BETA_INSTABILITY**: VXTLT as single cross-asset → need TLT/HYG/EMB daily returns

### P3 — Data must be acquired

| Missing Data | Series Needed | Unblocks |
|---|---|---|
| Intraday SPX (5-min) | yfinance intraday or TAQ | K_BIPOWER_GAP, K_REALIZED_JUMP upgrade |
| OTM options chain (SPX) | CBOE LiveVol or OptionMetrics | K_OTM_PUT_RICHNESS, K_SMILE_CURVATURE, K_GAMMA_STRESS |
| Cross-asset daily returns | TLT, HYG, EMB, UUP via yfinance | K_COVARIANCE_EIGENVECTOR_ROTATION, K_CORRELATION_NETWORK_REWIRING |
| Overnight gaps (open price) | SPX open from Bloomberg/yfinance | K_OVERNIGHT_GAP_FREQUENCY |
| GEX data | SpotGamma or derived from OI | K_GAMMA_STRESS |

---

## Recommended MVP Path

**Phase 1 (immediate):** Wire the 6 P1 proxies. This gives K its first non-NaN aggregation using CBOE volatility surface data. K_IV_SURFACE_DEFORMATION, K_SKEW_SLOPE, K_TERM_STRUCTURE_TWIST, K_VARIANCE_RISK_PREMIUM_INSTABILITY, K_CRASH_SKEW, K_VVIX → all derivable from existing panel.

**Phase 2 (next Harvester upgrade):** Add cross-asset ETF returns (TLT, HYG, EMB, UUP) to enable K_TRANSITION_INSTABILITY sub-proxies.

**Phase 3 (requires options data):** Full IV surface / OTM put data for K_OTM_PUT_RICHNESS, K_SMILE_CURVATURE, K_GAMMA_STRESS, K_BIPOWER_GAP.
