# Qlib Role Definition

**Date:** 2026-06-03
**Status:** PAPER / EXPERIMENTAL — no data flow, no artifacts

---

## Role

**Market Expression Validator**

Qlib's sole purpose in this framework is to answer: "When M/D/K/X_agg signals fire, do asset prices respond systematically?"

Qlib does NOT:
- Generate structural signals
- Write framework_output.json
- Replace Structural Replay
- Feed into SigmaVector
- Participate in governance

---

## Input

| Input | Source | Format |
|-------|--------|--------|
| Regime table | Structural Replay output | DataFrame: date × {M, D, K, X_agg, dominant, cofire, regime} |
| Asset returns | External (Yahoo/Tushare/ Wind) | DataFrame: date × asset_id → return |
| Factor data | External (Barra/Axioma) | DataFrame: date × factor_id → exposure (optional) |

## Output

| Output | Description |
|--------|-------------|
| Forward returns | Per-regime mean/median forward returns (21d, 63d, 126d) |
| IC / RankIC | Information Coefficient: correlation between signal and forward return |
| Long-short performance | Top quintile minus bottom quintile, conditioned on regime |
| Sector response | Which sectors respond most to each channel |
| Regime persistence | How long does each regime last? |

## Boundary Rules

1. **Qlib is read-only on framework outputs.** It reads regime tables; it does not write them.
2. **Qlib cannot write framework_output.json.** Its outputs go to `Output/sandbox/qlib/`.
3. **Qlib cannot modify SigmaVector.** It consumes SigmaVector; it does not produce it.
4. **Qlib cannot generate trading signals.** It produces statistical evidence, not trade recommendations.
5. **Qlib artifacts are sandbox-only.** They cannot be promoted to Data/ without explicit governance review.

## Current Status

| Component | Status |
|-----------|--------|
| Runner code | EXISTS (`ExternalTools/qlib_benchmark_runner/`) |
| Qlib installed | **NO** |
| Real data flow | **NO** |
| Training artifacts | **NO** |
| Backtest results | **NO** |
| Integration with Replay | **NO** |

## Status: **PAPER / EXPERIMENTAL**
