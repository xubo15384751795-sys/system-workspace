# tau_t - Latency

## 1. Definition

`tau_t` represents delays between shock arrival, observability, valuation update,
funding response, liquidation, and policy action.

## 2. What It Is Not

- Not transaction latency only.
- Not reporting lag only.
- Not a generic slow-moving variable.

## 3. Mechanism

Latency allows pressure to accumulate out of sight and can make eventual
realization more discontinuous.

## 4. Observable Traces

- reporting lags
- settlement delays
- policy response delay
- stale valuation update cycles

## 5. Benchmark Controls

- release-lag controls
- realized volatility
- funding spread controls

## 6. Rejection Gate

If latency-adjusted diagnostics do not change the timing or interpretation of
stress episodes, the latency channel should be treated as secondary.

## 7. Related Cases

- [2008 GFC](../cases/2008_GFC.md)
- [2022 LDI](../cases/2022_LDI.md)

## 8. Related Code

- `src/data/quality/manifest.py`
- `src/validation/walk_forward.py`

## 9. Paper Usage

Use to justify no-lookahead discipline and release-lag aware diagnostics.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
