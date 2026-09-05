# Benchmark Design

## 1. Purpose

Define comparison surfaces that can falsify or weaken structural claims.

## 2. Inputs

- benchmark series
- role tags
- frequency policy
- comparable target events or outcomes

## 3. Outputs

- benchmark panel
- residual controls
- ablation comparisons

## 4. Boundary Rules

- Broad stress benchmarks compare against `Sigma_t`; they do not define it.
- Benchmark victory is not required for formal architectural claims.
- Empirical dominance claims require no-lookahead and out-of-sample evidence.

## 5. Failure Modes

- benchmark leakage
- incomparable frequencies
- unregistered source transformations

## 6. Related Code

- `src/benchmarks/benchmark_registry.py`
- `src/benchmarks/benchmark_panel.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
