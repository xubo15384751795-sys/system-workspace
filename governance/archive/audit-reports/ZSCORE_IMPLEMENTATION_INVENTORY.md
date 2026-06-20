# Z-Score Implementation Inventory

**Date:** 2026-06-03
**Total implementations found:** 12

---

## Summary

| # | Status | File | Function | Window | Winsor | Freq-aware | Output |
|---|--------|------|----------|--------|--------|------------|--------|
| 1 | **ACTIVE** | proxy_builder.py | `_rolling_zscore` | 260w | ±3σ | ❌ | scalar |
| 2 | **ACTIVE** | structural_replay_v2.py | `_rolling_zscore` | 252d | ±4 clip | ❌ | Series |
| 3 | **ACTIVE** | structural_replay_v2.py | `_freq_aware_zscore` | freq-dep | ±4 clip | ✅ | Series |
| 4 | PAPER | fast_signal.py | `_rolling_zscore` | expanding | ❌ | ❌ | scalar |
| 5 | PAPER | fast_signal.py | `_expanding_zscore` | expanding | ❌ | ❌ | Series |
| 6 | PAPER | historical_replay.py | `rolling_zscore` | 52w | ❌ | ❌ | Series |
| 7 | PAPER | institutional_risk.py | `rolling_robust_zscore` | 52w | ❌ | ❌ | Series |
| 8 | PAPER | portfolio_baselines.py | `_expanding_zscore` | expanding | ❌ | ❌ | Series |
| 9 | OTHER | residualization.py | `zscore` | expanding | ❌ | ❌ | Series |
| 10 | OTHER | data_sources.py | `_zscore` | 260w | ±3σ | ❌ | Series |
| 11 | OTHER | gateway/bridge.py | `_zscore` | full-sample | ❌ | ❌ | Series |
| 12 | ARCHIVED | compute_proxies.py | `zscore` | 260w | ±3σ | ❌ | scalar |

---

## Detailed Inventory

### 1. proxy_builder.py::_rolling_zscore — ACTIVE

```python
def _rolling_zscore(self, series, window=260*7):  # 260 weeks in days
    # Winsorize at ±3σ of rolling window
    # Returns scalar (latest value only)
```

- **Window:** 260 weeks (1820 days)
- **Winsor:** ±3σ
- **Lookahead:** causal (uses last observation)
- **Output:** scalar (latest z only)
- **Used by:** Deformation ProxyBuilder for M/D/K/X channels
- **Canonical?:** Partially — correct window/winsor but scalar output

### 2. structural_replay_v2.py::_rolling_zscore — ACTIVE

```python
def _rolling_zscore(series, window=252, min_periods=126):
    mu = series.rolling(window, min_periods).mean()
    sigma = series.rolling(window, min_periods).std().replace(0, nan)
    return ((series - mu) / sigma).clip(-4, 4)
```

- **Window:** 252 days (1 year)
- **Winsor:** ±4 clip (not ±3σ winsor)
- **Lookahead:** causal rolling
- **Output:** Series
- **Used by:** structural_replay_v2.py for all channel z-scores
- **Canonical?:** Close — causal rolling + explicit min_periods, but different window/winsor

### 3. structural_replay_v2.py::_freq_aware_zscore — ACTIVE

```python
def _freq_aware_zscore(series, freq):
    # Resample to native cadence, compute z, ffill back to daily
    if freq == "daily": return _rolling_zscore(series, 252, 126)
    if freq in ("weekly", "monthly", "quarterly"):
        native = series.resample(rule).last()
        z_native = _rolling_zscore(native, window, min_periods)
        return z_native.reindex(series.index, method="ffill", limit=max_fill)
```

- **Window:** freq-dependent (252d/52w/12m/20q)
- **Winsor:** ±4 clip (via _rolling_zscore)
- **Lookahead:** causal + resample-aware
- **Output:** Series
- **Used by:** structural_replay_v2.py for all frequency-aware z-scores
- **Canonical?:** Closest to canonical — freq-aware + causal + Series output

### 4-8. PAPER implementations

| # | File | Window | Used by |
|---|------|--------|---------|
| 4 | fast_signal.py::_rolling_zscore | expanding | No active consumer |
| 5 | fast_signal.py::_expanding_zscore | expanding | No active consumer |
| 6 | historical_replay.py::rolling_zscore | 52w | No active consumer |
| 7 | institutional_risk.py::rolling_robust_zscore | 52w | No active consumer |
| 8 | portfolio_baselines.py::_expanding_zscore | expanding | No active consumer |

### 9-12. OTHER implementations

| # | File | Window | Notes |
|---|------|--------|-------|
| 9 | residualization.py::zscore | expanding | Diagnostic only |
| 10 | data_sources.py::_zscore | 260w | Legacy data layer |
| 11 | gateway/bridge.py::_zscore | full-sample | **LEGACY — full-sample, not causal** |
| 12 | compute_proxies.py::zscore | 260w | ARCHIVED — standalone script (moved to scripts/archive/) |

---

## Key Divergences

| Divergence | Impact | Files affected |
|-----------|--------|----------------|
| **Window: 260w vs 252d** | Different normalization baseline | proxy_builder vs replay_v2 |
| **Winsor: ±3σ vs ±4 clip** | Different outlier handling | proxy_builder vs replay_v2 |
| **Scalar vs Series** | proxy_builder returns latest only; replay returns full series | proxy_builder vs replay_v2 |
| **Freq-aware vs fixed** | Quarterly data gets wrong window if fixed | replay_v2 (has it) vs others (don't) |
| **Full-sample vs rolling** | bridge.py uses full history — look-ahead risk | bridge.py |
