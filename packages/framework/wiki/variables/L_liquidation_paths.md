# L_t - Liquidation Path Feasibility

## 1. Definition

`L_t` represents the available paths for selling, funding, hedging, rolling, or
transferring risk without forcing large discontinuous realization.

## 2. What It Is Not

- Not trading volume alone.
- Not market depth alone.
- Not a liquidity index by itself.

## 3. Mechanism

Liquidation paths contract when actors have fewer feasible sequences for
reducing exposure without moving prices, breaching constraints, or realizing losses.

## 4. Observable Traces

- market depth deterioration
- bid-ask widening
- funding access deterioration
- collateral liquidation pressure
- hedge availability decline

## 5. Benchmark Controls

- liquidity indexes
- bid-ask proxies
- funding spread controls

## 6. Rejection Gate

If `L_t` cannot be separated from ordinary liquidity controls, it should remain
descriptive rather than a distinct structural primitive.

## 7. Related Cases

- [2020 Treasury basis](../cases/2020_treasury_basis.md)
- [2022 LDI](../cases/2022_LDI.md)

## 8. Related Code

- `src/proxies/d_path_feasibility.py`
- `src/diagnostics/morphology_classifier.py`

## 9. Paper Usage

Use as primitive-layer grounding for `D_t` path feasibility.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
