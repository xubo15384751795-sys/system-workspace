# Forced Realization

## 1. Definition

Forced realization occurs when actors must recognize, sell, fund, or hedge
positions under constrained paths rather than chosen timing.

## 2. Structural Role

It converts `X_t` and `M_t` into observable stress when `D_t` contracts.

## 3. Observable Traces

- emergency liquidation
- loss crystallization
- margin or collateral calls
- forced policy facilities

## 4. Cases

- [2023 SVB](../cases/2023_SVB.md)
- [2022 LDI](../cases/2022_LDI.md)

## 5. Rejection Gate

If observed stress can be explained without timing constraint or path
contraction, forced realization should be treated as secondary.

## 6. Related Code

- `src/derivation/singular_detector.py`
- `src/operators/operator_registry.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
