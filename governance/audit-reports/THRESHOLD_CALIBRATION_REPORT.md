# Threshold Calibration Report

**Date:** 2026-06-03
**Training window:** 2007-01-01 to 2016-12-31

---

## Current vs Calibrated Thresholds

| Channel | Current (fixed) | Calibrated q90 (warning) | Calibrated q95 (critical) | Optimal (max Sharpe) |
|---------|----------------|--------------------------|---------------------------|---------------------|
| K positive | +1.00 | +1.66 | +2.17 | +1.50 |
| K negative | -1.00 | -1.32 | -1.50 | -1.50 |
| X_agg positive | +1.00 | +2.16 | +2.73 | +2.75 |
| X_agg negative | -1.00 | -1.40 | -1.49 | — |

**Current ±1.0 is BELOW the q50 (median) for some channels.** This means triggers fire when the channel is at or below its median value — that's not "stress", that's normal.

---

## Threshold Sensitivity: K negative_compression

| Threshold | Events | 60d Mean | Hit Rate | Sharpe Proxy |
|-----------|--------|----------|----------|--------------|
| -0.50 | 182 | +2.07% | 70% | 0.235 |
| -0.75 | 152 | +1.97% | 69% | 0.230 |
| **-1.00 (current)** | **107** | **+2.48%** | **70%** | **0.301** |
| -1.25 | 81 | +2.50% | 72% | 0.317 |
| **-1.50 (optimal)** | **47** | **+3.33%** | **72%** | **0.463** |
| -1.66 (q90) | 33 | +3.29% | 70% | 0.404 |
| -2.00 | 10 | +1.95% | 50% | 0.223 |

**Optimal K negative threshold: -1.50** (47 events, +3.33%, Sharpe 0.463)

---

## Threshold Sensitivity: X_agg positive_spike

| Threshold | Events | 60d Mean | Hit Rate | Sharpe Proxy |
|-----------|--------|----------|----------|--------------|
| +0.50 | 137 | +1.05% | 61% | 0.114 |
| +0.75 | 119 | +1.81% | 61% | 0.209 |
| **+1.00 (current)** | **99** | **+2.63%** | **66%** | **0.299** |
| +1.25 | 84 | +2.73% | 70% | 0.311 |
| +1.50 | 68 | +1.98% | 68% | 0.218 |
| +2.00 | 49 | +2.53% | 73% | 0.253 |
| **+2.16 (q90)** | **45** | **+3.28%** | **73%** | **0.333** |
| +2.75 (optimal) | ~20 | ~+4.0% | ~80% | 0.454 |

**Optimal X_agg positive threshold: +2.16 (q90)** (45 events, +3.28%, Sharpe 0.333)

---

## Recommendations

### K channel
- **Keep current -1.0** for backward compatibility (107 events)
- **Recommended: -1.50** for higher quality (47 events, +3.33% vs +2.48%)
- **Calibrated q90: -1.32** — close to current, minimal change

### X_agg channel
- **Current +1.0 is too loose** — fires on below-median readings
- **Recommended: +2.16 (q90)** for calibrated quality (45 events, +3.28%)
- **Alternative: +1.50** for moderate tightening (68 events, +1.98%)

### Sigma_t threshold
- Current: 1.5628 (from FRAMEWORK_CONTRACT)
- This is a regime classification threshold, not a trigger threshold
- Keep as-is for now

---

## Impact Assessment

| Change | Events Lost | Return Gain | Risk |
|--------|------------|-------------|------|
| K: -1.0 → -1.50 | 107 → 47 (-56%) | +2.48% → +3.33% (+34%) | Sample too small |
| X_agg: +1.0 → +2.16 | 99 → 45 (-55%) | +2.63% → +3.28% (+25%) | Sample borderline |
| K: -1.0 → -1.25 | 107 → 81 (-24%) | +2.48% → +2.50% (+1%) | Minimal improvement |

**Conservative recommendation:** Move X_agg from +1.0 to +1.25 (84 events, +2.73%). Keep K at -1.0.

**Aggressive recommendation:** Move both to calibrated q90 (K: -1.32, X_agg: +2.16). Higher quality but smaller sample.

---

## Artifacts

| File | Content |
|------|---------|
| `THRESHOLD_CALIBRATION_REPORT.md` | This report |
