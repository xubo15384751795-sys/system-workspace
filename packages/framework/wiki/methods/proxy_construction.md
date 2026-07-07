# Proxy Construction

## 1. Purpose

Construct structural proxy channels `M/D/K/X` from registered evidence without
benchmark contamination.

## 2. Inputs

- registered structural series
- channel role
- orientation and weights
- frequency policy
- no-lookahead policy

## 3. Outputs

- channel proxy values
- component diagnostics
- provenance and manifest references

## 4. Boundary Rules

- Benchmarks do not enter proxy core by default.
- Research corpus materials do not enter proxy construction unless registered as structured data.
- Proxy definitions do not redefine wiki variables.

## 5. Failure Modes

- benchmark leakage
- unregistered transformed data
- cross-loading that collapses morphology into one score

## 6. Related Code

- `src/proxies/`
- `src/derivation/proxy_builder.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
