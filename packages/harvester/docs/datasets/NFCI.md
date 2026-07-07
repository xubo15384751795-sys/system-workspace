# NFCI

## 1. Dataset Role

Benchmark/control. NFCI is not part of `Sigma_t` proxy core by default.

## 2. Source And Access

Federal Reserve Bank of Chicago / FRED where available. Register a manifest
before use in reports or paper outputs.

## 3. Frequency Policy

Use release-lag-aware weekly alignment. Do not forward-fill into earlier dates
than public availability.

## 4. Allowed Uses

- benchmark comparison
- residualization control
- falsification gate

## 5. Forbidden Uses

- default `Sigma_t` core construction
- proof of structural morphology by itself

## 6. Manifest Requirements

- data manifest under `data/manifests/`
- no-lookahead check under `tests/no_lookahead/` or equivalent test path

## 7. Related Code

- `src/benchmarks/benchmark_registry.py`
- `src/diagnostics/residualization.py`

## 8. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
