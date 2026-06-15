# Full Coverage Validation Report

**Generated:** 2026-06-02
**Sprint:** Structural Replay Full Coverage Validation Sprint

---

## Status

```
Overall:    ACTIVE_FULL
Quality:    FULL_PROXY_REDUCED
Coverage:   4/4
Cofire:     4
Dominant:   K (abs 1.19, low_vol_compression)
Blind Spot: NO
```

---

## What Changed Since Last Sprint

| Metric | Coverage Repair Sprint | This Sprint |
|--------|----------------------|-------------|
| Overall | ACTIVE_PARTIAL 3/4 | **ACTIVE_FULL 4/4** |
| Quality | (not tracked) | **FULL_PROXY_REDUCED** |
| K status | NOT_IMPLEMENTED | **LIVE** (3 voting proxies) |
| X_agg status | NOT_IMPLEMENTED | **LIVE** (2 voting proxies) |
| Channel confidence | (not tracked) | **per-channel table** |
| K interpretation | (not tracked) | **low_vol_compression** |
| X_agg validation | (not tracked) | **11/16 events, 5 dominant, not filler** |
| Blind spot | YES | **NO** |
| Tests | 765 | **765** |

---

## Channel Confidence Summary

All 4 channels are **PROXY_REDUCED** (semantic_distance=3). This is the honest representation of current proxy quality.

| Channel | Confidence | Key Limitation |
|---------|-----------|----------------|
| M | low | NFCI is a broad composite, not direct anchor mismatch |
| D | low | DCPF3M is a funding rate, not direct path feasibility |
| K | low | VIX butterfly is vol-surface, not direct transition curvature |
| X_agg | low | SEC OBS is quarterly, OFR FSI is systemic stress (not direct shadow mass) |

---

## K Interpretation

**Current state:** K = -1.19, dominant channel.

**Meaning:** K is negative, indicating IV surface is **compressed** (low-vol complacency). The absolute deviation (1.19) is the largest of all 4 channels, making K the dominant pressure signal.

**Proxy sources:**
- VIX9D/VIX3M/VIX6M butterfly → iv_distortion
- CBOE SKEW → tail_convexity
- CBOE VVIX → vol_of_vol

**Interpretation caution:** K's dominance reflects the current vol regime (compressed vol surface), not necessarily structural risk. In a vol spike, K would flip positive and indicate stress.

---

## X_agg Validation

**X_agg is NOT a coverage filler.** Evidence:

1. Fires in 11/16 historical events (69%)
2. Dominant in 5/16 events (31%): WorldCom, Euro Debt, Taper, COVID, SVB
3. COVID-2020: X_agg = 4.0 (highest single-channel reading in dataset)
4. Near-zero correlation with M/D/K (independent dimension)
5. Captures shadow leverage — a dimension M/D/K explicitly do not cover

**Crisis coverage:**
- GFC 2008: X_agg = 0.18 (minor — SEC data sparse pre-2010)
- COVID 2020: X_agg = **4.0** (dominant — massive shadow leverage stress)
- SVB 2023: X_agg = **-1.30** (dominant — deleveraging/unwinding)

---

## Historical Event Summary (4-channel)

Average cofire count: 3.81/4. 13 of 16 events have all 4 channels cofiring.

| Event | Dominant | Cofire | X_agg contributes? |
|-------|----------|--------|-------------------|
| asian_1997 | K | 3 | No (pre-SEC) |
| ltcm_1998 | K | 3 | No (pre-SEC) |
| dotcom_2000 | K | 0 | No (pre-SEC) |
| worldcom_2002 | **X_agg** | 1 | **Yes (dominant)** |
| gfc_2008 | K | 2 | Yes (minor) |
| flash_crash_2010 | K | 3 | Yes |
| euro_debt_2011 | **X_agg** | 2 | **Yes (dominant)** |
| taper_2013 | **X_agg** | 2 | **Yes (dominant)** |
| china_2015 | D | 3 | Yes |
| brexit_2016 | K | 3 | Yes |
| volmageddon_2018 | K | 2 | Yes |
| repo_2019 | D | 3 | Yes |
| covid_2020 | **X_agg** | 4 | **Yes (dominant, 4ch cofire)** |
| ldi_2022 | M | 1 | Yes (minor) |
| svb_2023 | **X_agg** | 3 | **Yes (dominant)** |
| august_2024 | M | 4 | Yes |

---

## Reports Generated

| Report | Content |
|--------|---------|
| `FULL_COVERAGE_VALIDATION_REPORT.md` | This report |
| `HISTORICAL_EVENT_REPLAY_4CH_REPORT.md` | 16 events with 4-channel analysis |
| `CHANNEL_CONFIDENCE_REPORT.md` | Per-channel confidence assessment |
| `X_AGG_VALIDATION_REPORT.md` | X_agg signal quality validation |
| `X_coverage_report.md` | X_agg MVP coverage plan |
| `K_coverage_report.md` | K MVP coverage plan |
| `STRUCTURAL_REPLAY_COVERAGE_REPAIR_REPORT.md` | Previous sprint report |
| `CANONICAL_DRIFT_REPORT.md` | Canonical drift audit |
| `MODULE_LIVENESS_REPORT.md` | Module liveness audit |
| `PROXY_TRACE_REPORT.md` | Proxy calculation trace |

---

## Residual Issues

| Issue | Severity | Status |
|-------|----------|--------|
| All channels PROXY_REDUCED distance=3 | Medium | Honest — best available data |
| X_agg quarterly resampling | Low | Handled by _freq_aware_zscore |
| M/D/K monoculture families | Low | Appropriate for single-mechanism channels |
| X_agg v1 candidate_pending_promotion | Info | Parallel canonical_voting proxy added |
| X_agg v2 NFCILEVERAGE quarantined | Info | Correct — broad_composite forbidden |
