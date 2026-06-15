# Qlib / GluonTS MVP Plan

**Date:** 2026-06-03
**Status:** PLAN — not yet executed

---

## Qlib MVP: Regime-Conditioned Forward Return Test

### Goal

Answer: "When M/D/K/X_agg enters regime X, what happens to asset returns over the next 21/63/126 days?"

### Steps

1. **Install Qlib** (`pip install pyqlib`)
2. **Prepare regime table** from Structural Replay output:
   - 16 events × 4 channels × regime label
   - Extend to full daily regime series (not just events)
3. **Prepare asset returns**:
   - SPX daily returns (from CBOE:SPX in Harvester panel)
   - Optionally: sector ETFs (XLF, XLE, XLK, etc.)
4. **Run regime-conditioned forward return test**:
   - For each regime (safe/watch/near_threshold/crossed):
     - Compute mean/median forward return
     - Compute IC (signal vs forward return correlation)
     - Compute long-short (top vs bottom quintile)
5. **Output**: `Output/sandbox/qlib/regime_forward_returns.md`

### Expected Output

| Regime | SPX 21d mean | SPX 63d mean | IC | Long-short |
|--------|-------------|-------------|-----|-----------|
| safe | ? | ? | ? | ? |
| watch | ? | ? | ? | ? |
| near_threshold | ? | ? | ? | ? |
| crossed | ? | ? | ? | ? |

### Precondition

- Qlib installed
- Full daily regime series (not just 16 event dates)
- SPX daily returns in Harvester panel (already available: CBOE:SPX)

### Estimated Effort

1-2 days

---

## GluonTS MVP: Channel Forecast

### Goal

Answer: "Given M/D/K/X_agg history, where will each channel be in 21 days?"

### Steps

1. **Prepare channel time series** from Structural Replay:
   - Daily M/D/K/X_agg z-scores (from replay output)
   - 260-week history
2. **Train simple model**:
   - Start with Seasonal Naive (already implemented)
   - Upgrade to DeepAR or SimpleFeedForward if data sufficient
3. **Generate forecasts**:
   - 21d ahead for each channel
   - 80% / 95% confidence intervals
4. **Validate**:
   - Backtest: train on data up to t, forecast t+21, compare to actual
   - Compute RMSE, MAE, coverage probability
5. **Output**: `Output/sandbox/gluonts/channel_forecast.md`

### Expected Output

| Channel | Current | 21d forecast | 80% CI | RMSE |
|---------|---------|-------------|--------|------|
| M | -0.75 | ? | ? | ? |
| D | -0.88 | ? | ? | ? |
| K | -1.19 | ? | ? | ? |
| X_agg | -0.46 | ? | ? | ? |

### Precondition

- GluonTS installed (`pip install gluonts`)
- Full daily channel series from replay

### Estimated Effort

2-3 days

---

## What These MVPs Do NOT Do

| Not doing | Reason |
|-----------|--------|
| Stock-level forecasting | Out of scope — channels, not assets |
| Trading signal generation | Requires separate governance |
| Real-time deployment | Batch validation only |
| Integration into framework_output | Sandbox only |
| Model optimization | MVP first, optimize later |

---

## Status

Both Qlib and GluonTS remain **PAPER / EXPERIMENTAL** until:
1. Installed and runnable
2. Real data flows through them
3. Artifacts produced
4. Validated against held-out data
5. Governance review passed
