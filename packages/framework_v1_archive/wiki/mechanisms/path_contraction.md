# Path Contraction

## 1. Definition

Path contraction occurs when feasible hedging, funding, liquidation, or policy
response paths shrink under stress.

## 2. Structural Role

It lowers `D_t` and can convert manageable mismatch into forced realization.

## 3. Observable Traces

- reduced market depth
- funding access deterioration
- crowded liquidation routes
- hedge-basis instability

## 4. Cases

- [2020 Treasury basis](../cases/2020_treasury_basis.md)
- [2022 LDI](../cases/2022_LDI.md)

## 5. Rejection Gate

If path-contraction proxies are indistinguishable from generic liquidity
benchmarks, the mechanism should be narrowed.

## 6. Related Code

- `src/proxies/d_path_feasibility.py`
- `src/operators/operator_diagnostics.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
