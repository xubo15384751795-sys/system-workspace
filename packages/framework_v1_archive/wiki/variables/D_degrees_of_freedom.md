# D_t - Effective Degrees Of Freedom

## 1. Definition

`D_t` measures feasible pricing, hedging, funding, liquidation, and intervention
paths available to actors.

## 2. What It Is Not

- Not market liquidity alone.
- Not depth alone.
- Not an abstract dimension count directly observed in data.

## 3. Mechanism

`D_t` falls when actors lose feasible sequences for adapting to shocks without
forced realization or severe price impact.

## 4. Observable Traces

- hedge basis deterioration
- funding access contraction
- market depth deterioration
- collateral liquidation constraints

## 5. Benchmark Controls

- liquidity benchmarks
- bid-ask proxies
- funding spread controls

## 6. Rejection Gate

If `D_proxy` cannot separate path feasibility from generic liquidity stress, the
interpretation should be narrowed.

## 7. Related Cases

- [2020 Treasury basis](../cases/2020_treasury_basis.md)
- [2022 LDI](../cases/2022_LDI.md)

## 8. Related Code

- `src/proxies/d_path_feasibility.py`
- `src/diagnostics/structural_diagnostic.py`

## 9. Paper Usage

Core diagnostic channel. Use "effective" degrees of freedom, not direct manifold dimension.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
