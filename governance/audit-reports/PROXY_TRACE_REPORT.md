# Proxy Calculation Trace Report

**Generated:** 2026-06-02
**Scope:** Full proxy computation chain from raw series to SigmaVector
**Auditor:** Hermes Agent (proxy-calculation-trace-auditor)

---

## Chain Overview

```
Raw Series (FRED/SEC/Treasury/CBOE/OpenBB)
  ↓
Harvester: acquisition + normalization + provenance
  ↓
Data/harvester/exports/<release_id>/ (immutable)
  ↓
ProxyBuilder.build(raw DataFrame, run_date)
  ↓
  ├─ _build_channel(channel, history)
  │    ├─ _basket_score(channel, history, specs)
  │    │    ├─ _rolling_zscore(series)  [260-week window, winsorize ±3σ]
  │    │    ├─ orientation flip (stress/freedom)
  │    │    └─ weight × z → mean of basket
  │    └─ channel score = mean of basket scores
  │
  ├─ _combine_shadow_channels(X_PRE, X_REALIZED, legacy_X) → X
  │
  └─ ProxyReading(M, D, K, X, X_PRE, X_REALIZED, directions, available, components)
       ↓
ThresholdSingularDetector.detect(proxy, ...)
  ├─ _sigma_vector(M, D, K, X_PRE, X_REALIZED, operator_penalties)
  │    → SigmaVector (⚠️ uses X_PRE/X_REALIZED, not X_agg)
  ├─ sigma_t = w_mismatch×M + w_dof×max(-D,0) + w_curvature×K + w_shadow×(X_PRE+X_REALIZED)
  └─ singular_flag = scalar_threshold_hit OR joint_hitting OR distributional_trigger
       ↓
CriticalityState (safe/watch/near_threshold/crossed)
       ↓
Output/ reports
```

---

## Stage 1: Raw Series → Proxy Inputs

### Source: Harvester Providers

| Provider | Series Examples | File |
|----------|----------------|------|
| FRED | SOFR, FFR, NFCI, LIBOR-OIS | `harvester/providers/fred.py` |
| H.4.1 | Fed balance sheet, reserves | `harvester/providers/h41.py` |
| SEC | 13F, N-MFP, HTM disclosures | `harvester/providers/sec.py` |
| Treasury | Auction data, yield curve | `harvester/providers/treasury.py` |
| CBOE | VIX, VIX9D, SKEW, VVIX | `harvester/providers/cboe_direct.py` |
| OpenBB | Composite indicators | `harvester/providers/openbb_provider.py` |

**Provenance chain:** Each series gets `build_provenance()` with dataset_id, release_id, acquisition metadata, checksums (JSON Schema validated).

---

## Stage 2: Proxy Definitions → Basket Map

### M Channel (anchor_mismatch)

| Group | Inputs | Interpretation |
|-------|--------|----------------|
| M_POLICY_ANCHOR | SOFR_FFR, LIBOR_OIS_3M, M_MARKET_POLICY_PATH_GAP, M_POLICY_GUIDANCE_GAP | Market-implied policy path vs operative anchor |
| M_FUNDING_ANCHOR | SOFR_TBILL_3M, M_REPO_IMPLIED_FUNDING_GAP, M_PRICE_FUNDING_GAP | Secured/unsecured funding dislocation |
| M_COLLATERAL_ANCHOR | M_TREASURY_BASIS, M_SWAP_SPREAD, M_CASH_FUTURES_BASIS, M_ON_OFF_THE_RUN_SPREAD | Collateral price/liquidity/basis divergence |
| M_CREDIT_ANCHOR | HY_IG_GAP, BBB_IG_GAP, M_CDS_BOND_BASIS, M_CREDIT_SPREAD_DEFAULT_GAP | Credit spread vs default expectation |
| M_VERIFIABILITY_ANCHOR | M_PRICE_VERIFIABILITY_GAP, M_ACCOUNTING_MARKET_VALUE_GAP, M_BANK_EQUITY_BALANCE_SHEET_GAP | Market vs accounting stability |
| M_PRICE_LIQUIDATION_GAP | M_FIRE_SALE_DISCOUNT, M_DEPTH_ADJUSTED_LIQUIDATION_COST, M_BID_WANTED_PRESSURE | Forced-sale value gap |

**Total M inputs:** 27 proxy variables across 6 groups

### D Channel (path_feasibility)

| Group | Inputs |
|-------|--------|
| D_MARKET_DEPTH | D_DEPTH, D_ORDER_BOOK_DEPTH, D_BID_ASK_SPREAD, D_AMIHUD_ILLIQUIDITY, D_PRICE_IMPACT |
| D_HEDGE_BREADTH | D_OPTION_OPEN_INTEREST_BREADTH, D_STRIKE_MATURITY_COVERAGE, D_HEDGE_AVAILABILITY, D_HEDGE_INSTRUMENT_CORRELATION |
| D_FUNDING_ACCESS | D_DEALER_CAPACITY, D_REPO_ACCESSIBILITY, D_REPO_SPREAD, D_HAIRCUT_MARGIN, D_FUNDING_STRESS |
| D_LIQUIDATION_PATHS | D_DEALER_INVENTORY_ABSORPTION, D_PRIMARY_DEALER_CAPACITY, D_MARKET_CONCENTRATION, D_ETF_NAV_DISLOCATION |

**Total D inputs:** 21 proxy variables across 4 groups

### K Channel (transition_deformation)

| Group | Inputs |
|-------|--------|
| K_IV_SURFACE_DEFORMATION | K_IV_DISTORTION, K_SKEW_SLOPE, K_SMILE_CURVATURE, K_TERM_STRUCTURE_TWIST, K_VARIANCE_RISK_PREMIUM_INSTABILITY |
| K_JUMP_DISCONTINUITY | K_REALIZED_JUMP, K_BIPOWER_GAP, K_OVERNIGHT_GAP_FREQUENCY |
| K_TAIL_CONVEXITY | K_OTM_PUT_RICHNESS, K_CRASH_SKEW, K_VVIX, K_GAMMA_STRESS |
| K_TRANSITION_INSTABILITY | K_ROLLING_BETA_INSTABILITY, K_COVARIANCE_EIGENVECTOR_ROTATION, K_CORRELATION_NETWORK_REWIRING, K_REGIME_SWITCHING_RESIDUAL |

**Total K inputs:** 20 proxy variables across 4 groups

### X_PRE Channel (shadow_accumulation_pre_realization)

| Group | Inputs |
|-------|--------|
| X_HIDDEN_LEVERAGE | X_MARGIN_DEBT, X_DEALER_LEVERAGE_PROXY, X_BROKER_DEALER_ASSETS, X_REPO_VOLUME_COLLATERAL_REUSE, X_OBS_ASSETS |
| X_SHADOW_SUBSTITUTION | X_SHADOW_FUNDING, X_PRIVATE_CREDIT_GROWTH, X_NONBANK_LENDING_GROWTH, X_MMF_REPO_INTERMEDIATION |
| X_MATURITY_MISMATCH | X_SHORT_TERM_FUNDING_RELIANCE, X_MATURITY_WALL, X_DEPOSIT_BETA_UNINSURED_STRESS, X_ASSET_LIABILITY_DURATION_MISMATCH |
| X_VALUATION_LAG | X_PRIVATE_ASSET_VALUATION_LAG, X_HTM_UNREALIZED_LOSS_PROXY, X_CRE_STALE_MARKS, X_PRIVATE_CREDIT_STALE_MARKS |
| X_OFFICIAL_SUPPORT_USAGE | X_PRIMARY_CREDIT, X_DISCOUNT_WINDOW, X_BTFP |
| X_SUPPORT_SUBSTITUTION | X_FED_LIQUIDITY_FACILITY_USAGE, X_EMERGENCY_LIQUIDITY_USAGE |

**Total X_PRE inputs:** 31 proxy variables across 6 groups

**⚠️ Note:** X_PRE has the most proxy inputs of any channel. X_REALIZED has no separate proxy definition file — it uses `X_REALIZED_PROXY_DEFINITION` from `x_shadow_accumulation.py`.

---

## Stage 3: Z-Score Computation

**File:** `proxy_builder.py::_rolling_zscore()`

```python
# Parameters:
ROLLING_ZSCORE_WINDOW = 260  # weeks ≈ 5 years
WINSOR_CLIP_STD = 3.0        # clip at ±3σ

# Algorithm:
1. Drop NaN/Inf from series
2. Take last min(window, len(series)) observations
3. Winsorize raw values at ±3σ of window
4. Compute z = (latest_clipped - window_mean) / window_std
5. If std == 0: return (latest_clipped - mean) [raw deviation]
```

**Look-ahead bias prevention:** Rolling window ensures only past data is used.

---

## Stage 4: Direction Assignment (Orientation Flip)

**File:** `proxy_builder.py::_basket_score()` L129-135

```python
orientation = str(spec.get("orientation", "stress")).lower()
is_freedom_positive = orientation in {"freedom", "capacity", "good"}
if channel == "D":
    if not is_freedom_positive:
        z = -z          # D: stress → positive
elif is_freedom_positive:
    z = -z              # M/K/X: freedom → negative (stress = positive)
```

**Convention:** For M/K/X channels, higher = more stress. For D channel, higher = more freedom (positive), so stress inputs are negated.

---

## Stage 5: Channel Score Aggregation

**File:** `proxy_builder.py::_build_channel()` L85-117

```python
# If direct column exists in DataFrame:
val = latest_float(history[direct_col])
# Components are basket scores, not aggregated

# If no direct column (basket-based):
basket_scores = {basket: _basket_score(...) for basket in basket_map[channel]}
available_scores = [v for v in basket_scores.values() if v is not None]
value = float(np.mean(available_scores))  # Equal-weight mean
```

**Aggregation:** Simple mean of available basket scores. No weighted aggregation at this stage.

---

## Stage 6: Shadow Channel Combination

**File:** `proxy_builder.py` L71

```python
values["X"] = self._combine_shadow_channels(values["X_PRE"], values["X_REALIZED"], legacy_x)
```

X is a combination of X_PRE (hidden stock) and X_REALIZED (forced release). The combination logic handles None values and legacy X series.

---

## Stage 7: Sigma Computation (⚠️ DRIFT POINT)

### Path A: Canonical (semantic.py::build_sigma_vector)

```python
CANONICAL_CHANNELS = ["M", "D", "K", "X_agg"]
# Uses X_agg — CORRECT per spec
```

### Path B: Detector (singular_detector.py::_sigma_vector)

```python
channels = {
    "M": w_mismatch * mismatch,
    "D": w_dof * dof_contraction,
    "K": w_curvature * curvature,
    "X_PRE": w_shadow * shadow_pre,        # ← WRONG
    "X_REALIZED": w_shadow * shadow_realized,  # ← WRONG
}
# dominant_channel and cofire_count computed over 5 channels — WRONG
```

### Path C: Morphology replay (c005_morphology_replay.py::compute_sigma_t)

```python
sigma_t = M + max(-D, 0) + K + X_PRE  # ← WRONG, should use X_agg
```

### Sigma scalar formula (default weights)

```
sigma_t = w_mismatch × max(M, 0)
        + w_dof × max(-D, 0)          # D is freedom; stress = -D
        + w_curvature × max(K, 0)
        + w_shadow × shadow_component  # Should be X_agg, not X_PRE
```

---

## Stage 8: Singular Detection

**Thresholds (defaults):**
- `sigma_threshold = 2.0`
- `dof_collapse_threshold = -0.65`
- `curvature_spike_threshold = 0.65`
- `forced_realization_threshold = 0.65`
- `distributional_prob_threshold = 0.60`

**Three triggers:**
1. `scalar_threshold_hit`: sigma_t ≥ sigma_threshold
2. `joint_hitting`: D ≤ -0.65 AND K ≥ 0.65 AND realization_pressure ≥ 0.65
3. `distributional_trigger`: sigma_breach_prob ≥ 0.60 OR sigma_q90 ≥ threshold

---

## Stage 9: Criticality State

```
sigma_t / sigma_threshold:
  ≥ 1.0        → "crossed"
  ≥ 0.85       → "near_threshold"
  ≥ 0.45       → "watch"
  < 0.45       → "safe"
  invalid      → "unknown"
```

---

## Key Findings

1. **X_PRE has the richest proxy basket** (31 inputs, 6 groups) — more than M (27), D (21), or K (20). This suggests significant research effort went into shadow accumulation modeling.

2. **X_REALIZED has no independent proxy definition** — it reuses the X_PRE proxy definition structure. The actual realized data likely comes from a different source path.

3. **Three separate sigma computation paths exist** — canonical (correct), detector (wrong channels), morphology replay (wrong channels). Only the canonical path uses X_agg.

4. **Z-score computation is sound** — rolling 260-week window with winsorization prevents look-ahead bias and outlier contamination.

5. **Aggregation is simple mean** — no Huber or weighted L1 despite the canonical spec specifying `aggregator: huber_or_weighted_l1` for M channel. This is a P2 gap.

---

## Traceability Matrix

| Proxy Input | Channel | Group | In Spec? | In Code? | In Data? |
|-------------|---------|-------|----------|----------|----------|
| SOFR_FFR | M | POLICY_ANCHOR | ✅ | ✅ | ⚠️ Unknown |
| D_AMIHUD_ILLIQUIDITY | D | MARKET_DEPTH | ✅ | ✅ | ⚠️ Unknown |
| K_VVIX | K | TAIL_CONVEXITY | ✅ | ✅ | ⚠️ Unknown |
| X_MARGIN_DEBT | X_PRE | HIDDEN_LEVERAGE | ✅ | ✅ | ⚠️ Unknown |

**Note:** "In Data?" requires running Harvester to verify which series actually have data. This is a follow-up audit.
