# S_t - Subject Configuration

## 1. Definition

`S_t` represents the composition and concentration of relevant market subjects:
investors, dealers, banks, funds, policy actors, and balance-sheet holders.

## 2. What It Is Not

- Not a headcount.
- Not market capitalization.
- Not a direct systemic-risk index.

## 3. Mechanism

Subject configuration matters when similar shocks propagate differently because
the holders, intermediaries, and constrained actors are different.

## 4. Observable Traces

- holder concentration
- dealer balance-sheet concentration
- fund-flow concentration
- issuer/investor type mix

## 5. Benchmark Controls

- broad market concentration indexes
- bank equity indexes
- fund flow aggregates

## 6. Rejection Gate

If subject concentration has no incremental diagnostic value after ordinary
market concentration controls, the interpretation should be weakened.

## 7. Related Cases

- [2023 SVB](../cases/2023_SVB.md)
- [2022 LDI](../cases/2022_LDI.md)

## 8. Related Code

- `src/observability/required_evidence_registry.py`
- `src/research/local_state_spaces.py`

## 9. Paper Usage

Use as primitive-layer context underneath `M/D/K/X`, not as a direct crisis score.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
