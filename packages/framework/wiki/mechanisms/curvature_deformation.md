# Curvature Deformation

## 1. Definition

Curvature deformation is instability in the local transition map from shock to
feasible next state.

## 2. Structural Role

It raises `K_t` and explains why nearby regimes can react sharply differently to
similar shocks.

## 3. Observable Traces

- transition residual instability
- covariance eigenvector rotation
- IV surface deformation
- regime classifier instability

## 4. Cases

- [2020 Treasury basis](../cases/2020_treasury_basis.md)
- [2024-08-05 yen carry stress](../cases/2024_08_05_yen_carry.md)

## 5. Rejection Gate

If curvature proxies have no incremental value after volatility, jump, and tail
controls, the interpretation is weakened.

## 6. Related Code

- `src/proxies/k_transition_deformation.py`
- `src/diagnostics/rejection_gates.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
