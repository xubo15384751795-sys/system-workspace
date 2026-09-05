# K_t - Transition Curvature / Transition Deformation

## 1. Definition

`K_t` represents local deformation in the transition map from shocks to feasible
next states.

## 2. What It Is Not

- Not volatility.
- Not jump intensity.
- Not tail risk.
- Not VIX.

## 3. Mechanism

`K_t` rises when similar shocks produce sharply different propagation paths
across nearby regimes.

## 4. Observable Traces

- IV surface deformation
- rolling beta instability
- covariance eigenvector rotation
- correlation network rewiring
- regime transition residuals

## 5. Benchmark Controls

- VIX
- MOVE
- realized volatility
- jump proxy
- tail proxy

## 6. Rejection Gate

If `K_proxy` has no incremental value after volatility, jump, and tail controls,
its curvature interpretation is weakened.

## 7. Related Cases

- [2020 Treasury basis](../cases/2020_treasury_basis.md)
- [2022 LDI](../cases/2022_LDI.md)
- [2024-08-05 yen carry stress](../cases/2024_08_05_yen_carry.md)

## 8. Related Code

- `src/proxies/k_transition_deformation.py`
- `src/diagnostics/residualization.py`

## 9. Paper Usage

Used as a diagnostic proxy, not as directly observed Riemannian curvature.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
