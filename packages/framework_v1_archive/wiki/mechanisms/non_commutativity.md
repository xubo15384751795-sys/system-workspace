# Non-Commutativity

## 1. Definition

Non-commutativity means event order matters: applying event operators in
different orders can produce different structural states.

## 2. Structural Role

It supports the critique of scalar state summaries that ignore path order.

## 3. Observable Traces

- order-swap output separation
- commutator vector magnitude
- sequence-specific amplification

## 4. Cases

- [1998 LTCM](../cases/1998_LTCM.md)
- [2020 Treasury basis](../cases/2020_treasury_basis.md)

## 5. Rejection Gate

If event-order swaps do not change structural outputs, this mechanism should be
used cautiously for the studied window.

## 6. Related Code

- `src/operators/operator_algebra.py`
- `src/operators/operator_diagnostics.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
