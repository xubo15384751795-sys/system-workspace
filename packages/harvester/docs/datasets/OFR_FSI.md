# OFR FSI

## 1. Dataset Role

Benchmark/control. OFR FSI is a broad stress comparator, not default proxy core.

## 2. Source And Access

Office of Financial Research public data. Register a manifest before report or
paper use.

## 3. Frequency Policy

Use native-release timing and record any aggregation or alignment.

## 4. Allowed Uses

- broad stress comparison
- residualization control
- rejection gate

## 5. Forbidden Uses

- unregistered `Sigma_t` construction
- direct evidence of `M/D/K/X` morphology

## 6. Manifest Requirements

- data manifest
- no-lookahead check
- benchmark-role tag

## 7. Related Code

- `src/benchmarks/benchmark_registry.py`

## 8. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
