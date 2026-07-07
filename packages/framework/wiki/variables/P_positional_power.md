# P_t - Positional Power

## 1. Definition

`P_t` represents the ability of actors to delay, redirect, absorb, or force
realization because of balance sheet, policy, market-making, or legal position.

## 2. What It Is Not

- Not political power in general.
- Not size alone.
- Not moral judgment.

## 3. Mechanism

High positional power can postpone realization; collapsing positional power can
turn latent pressure into forced sales or policy intervention.

## 4. Observable Traces

- dealer capacity changes
- central-bank facility usage
- concentrated collateral dependency
- margin and haircut changes

## 5. Benchmark Controls

- dealer balance-sheet proxies
- funding stress indicators
- policy facility usage controls

## 6. Rejection Gate

If positional-power proxies cannot be distinguished from leverage or funding
stress, the interpretation should be weakened.

## 7. Related Cases

- [1998 LTCM](../cases/1998_LTCM.md)
- [2020 Treasury basis](../cases/2020_treasury_basis.md)

## 8. Related Code

- `src/operators/operator_diagnostics.py`
- `src/research/structural_mechanism_library.py`

## 9. Paper Usage

Use as a primitive behind path contraction and forced realization.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
