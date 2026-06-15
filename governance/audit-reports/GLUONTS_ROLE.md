# GluonTS Role Definition

**Date:** 2026-06-03
**Status:** PAPER / EXPERIMENTAL — no data flow, no artifacts

---

## Role

**State Transition Forecaster**

GluonTS's sole purpose is to forecast M/D/K/X_agg channel trajectories — not stock prices, not trading signals.

GluonTS does NOT:
- Generate trading signals
- Replace Structural Replay
- Write framework_output.json
- Feed into SigmaVector directly
- Predict stock returns

---

## Input

| Input | Source | Format |
|-------|--------|--------|
| Channel time series | Structural Replay | DataFrame: date × {M, D, K, X_agg} z-scores |
| Proxy components | Replay output | DataFrame: date × proxy_id → value |
| Regime labels | Replay output | Series: date → regime (safe/watch/near_threshold/crossed) |

## Output

| Output | Description |
|--------|-------------|
| Forecast mean | Point forecast for each channel (21d, 63d horizon) |
| Confidence interval | 80% / 95% prediction bands |
| Transition probability | P(regime_t+h = crossed | regime_t = watch) |
| Regime duration forecast | Expected time in current regime |

## Boundary Rules

1. **GluonTS forecasts channels, not assets.** It predicts where M/D/K/X_agg will go, not where SPX will go.
2. **GluonTS cannot generate trading signals.** Forecast → signal conversion is a separate, explicit step with its own governance.
3. **GluonTS cannot write framework_output.json.** Its outputs go to `Output/sandbox/gluonts/`.
4. **GluonTS outputs are advisory.** They inform, they do not decide.
5. **No forecast enters SigmaVector.** SigmaVector is computed from realized data, not forecasts.

## Current Status

| Component | Status |
|-----------|--------|
| Code | EXISTS (`Workbench/src/ml/gluonts_regime_forecaster.py`) |
| Backend | Seasonal Naive (fallback — no real GluonTS model trained) |
| Real data flow | **NO** |
| Training artifacts | **NO** |
| Forecast results | **NO** |
| Integration with Replay | **NO** |

## Status: **PAPER / EXPERIMENTAL**
