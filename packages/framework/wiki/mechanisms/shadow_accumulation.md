# Shadow Accumulation

## 1. Definition

Shadow accumulation is the buildup of hidden, delayed, or poorly verified risk
mass before observable realization.

## 2. Structural Role

It raises `X_t`, especially when verifiability is low and realization can be
deferred.

## 3. Observable Traces

- unrealized losses
- emergency-credit use after stress
- maturity mismatch
- stale valuation pockets

## 4. Cases

- [2008 GFC](../cases/2008_GFC.md)
- [2023 SVB](../cases/2023_SVB.md)

## 5. Rejection Gate

If shadow proxies only mirror leverage benchmarks, the mechanism remains
contextual rather than core empirical evidence.

## 6. Related Code

- `src/proxies/x_shadow_accumulation.py`
- `src/derivation/structural_layers.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
