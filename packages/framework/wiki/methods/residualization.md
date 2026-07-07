# Residualization

## 1. Purpose

Test whether structural channels retain diagnostic information after controlling
for broad stress, volatility, jump, tail, liquidity, or funding benchmarks.

## 2. Inputs

- proxy channel history
- benchmark/control panel
- aligned frequency policy

## 3. Outputs

- residual diagnostics
- incremental information metrics
- rejection-gate flags

## 4. Boundary Rules

- Controls are not proxy core.
- Residual value is diagnostic evidence, not automatic paper validation.

## 5. Failure Modes

- lookahead alignment
- overfitting small windows
- benchmark leakage into proxy construction

## 6. Related Code

- `src/diagnostics/residualization.py`
- `src/research/incremental_information.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
