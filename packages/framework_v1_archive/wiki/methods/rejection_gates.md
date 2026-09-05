# Rejection Gates

## 1. Purpose

Make weakening and rejection conditions explicit before paper claims expand.

## 2. Inputs

- incremental information metrics
- residual diagnostics
- event coherence checks
- portfolio validation metrics when portfolio language appears

## 3. Outputs

- rejection flags
- weakened claim language
- report notes

## 4. Boundary Rules

- Failed gates weaken claims.
- Passing a gate is not automatic proof.
- Rejected claims remain visible in the registry.

## 5. Failure Modes

- ignoring negative results
- converting exploratory metrics into core claims
- claiming portfolio value without backtests

## 6. Related Code

- `src/diagnostics/rejection_gates.py`
- `src/claims/claim_guard.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
