# Canonical Z-Score v1 Specification

**Date:** 2026-06-03
**Status:** SPEC — comparison mode only, not yet deployed

---

## Definition

```
canonical_zscore_v1(series, freq="daily") → (z_score: pd.Series, metadata: dict)
```

### Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **window** | frequency-dependent (see table) | Avoid look-ahead bias; match data cadence |
| **winsor_clip** | ±3σ | Standard robust statistics; proxy_builder.py precedent |
| **min_periods** | window / 2 | Ensure statistical stability |
| **method** | causal rolling | No future data leakage |
| **ddof** | 0 | Population std (consistent with proxy_builder.py) |
| **output** | pd.Series | Full time series, not scalar |

### Frequency-Dependent Windows

| freq | window (obs) | min_periods | Equivalent Time |
|------|-------------|-------------|-----------------|
| daily | 252 | 126 | ~1 year trading days |
| weekly | 52 | 26 | ~1 year weeks |
| monthly | 12 | 6 | ~1 year months |
| quarterly | 20 | 8 | ~5 year quarters |

### Algorithm

```python
def canonical_zscore_v1(series, freq="daily"):
    WINDOW_MAP = {"daily": (252, 126), "weekly": (52, 26), "monthly": (12, 6), "quarterly": (20, 8)}
    window, min_periods = WINDOW_MAP[freq]
    
    # 1. Winsorize raw values at ±3σ of rolling window
    mu_raw = series.rolling(window=window, min_periods=min_periods).mean()
    sigma_raw = series.rolling(window=window, min_periods=min_periods).std(ddof=0)
    lo = mu_raw - 3 * sigma_raw
    hi = mu_raw + 3 * sigma_raw
    winsorized = series.clip(lo, hi)
    
    # 2. Compute z-score on winsorized series
    mu = winsorized.rolling(window=window, min_periods=min_periods).mean()
    sigma = winsorized.rolling(window=window, min_periods=min_periods).std(ddof=0).replace(0, np.nan)
    z = (winsorized - mu) / sigma
    
    # 3. Clip extreme values
    z = z.clip(-4, 4)
    
    # 4. Metadata
    metadata = {
        "method": "canonical_zscore_v1",
        "window": window,
        "min_periods": min_periods,
        "winsor_clip": 3.0,
        "ddof": 0,
        "freq": freq,
        "lookahead_safe": True,
        "valid_observations": z.notna().sum(),
    }
    
    return z, metadata
```

### Key Properties

1. **Causal:** Only uses data up to time t to compute z(t)
2. **Winsorized:** Clips raw values at ±3σ before computing z
3. **Frequency-aware:** Window scales to data cadence
4. **Explicit missing:** Returns NaN when insufficient data (not 0)
5. **Bounded:** Final z clipped to [-4, +4]
6. **Auditable:** Returns metadata alongside z-score

### Differences from Existing Implementations

| Property | canonical_zscore_v1 | proxy_builder | replay_v2 | compute_proxies |
|----------|--------------------|--------------|-----------|-----------------|
| Window | 252d / 52w / 12m / 20q | 260w fixed | 252d fixed | 260w fixed |
| Winsor | ±3σ | ±3σ | ±4 clip | ±3σ |
| min_periods | window/2 | implicit | explicit | 4 |
| Freq-aware | ✅ | ❌ | ✅ | ❌ |
| Output | Series + metadata | scalar | Series | scalar |
| Lookahead | causal rolling | causal (last obs) | causal rolling | causal (last obs) |

### Migration Path

Phase 1: Comparison mode only (this spec)
Phase 2: Wire canonical_zscore_v1 into structural_replay_v2.py as optional
Phase 3: Switch replay to canonical_zscore_v1
Phase 4: Migrate proxy_builder.py (scalar → Series)
Phase 5: Migrate other implementations
