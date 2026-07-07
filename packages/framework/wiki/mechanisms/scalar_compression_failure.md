# Scalar Compression Failure

## 1. Definition

Scalar compression failure occurs when a single stress score hides materially
different structural morphologies.

## 2. Structural Role

It motivates the separation of `M/D/K/X` and the claim that the same benchmark
level can correspond to different propagation paths.

## 3. Observable Traces

- same benchmark level with different channel profiles
- benchmark residuals explained by morphology
- case sequences that diverge despite similar scalar stress

## 4. Cases

- [2020 Treasury basis](../cases/2020_treasury_basis.md)
- [2023 SVB](../cases/2023_SVB.md)

## 5. Rejection Gate

If channel profiles add no incremental diagnostic value over broad benchmarks,
the compression-failure claim is weakened.

## 6. Related Code

- `src/diagnostics/residualization.py`
- `src/research/incremental_information.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
