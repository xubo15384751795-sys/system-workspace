# 2020 Treasury Basis - Safe-Asset Liquidity And Basis Unwind

## 1. Event Summary

In March 2020, Treasury-market functioning deteriorated while basis and
relative-value trades faced funding and liquidation pressure.

## 2. Structural Diagnosis

- `M`: elevated, cash/futures and funding anchors diverged
- `D`: collapsing, dealer and liquidation paths narrowed
- `K`: high, safe-asset response became nonlinear
- `X`: high, leveraged relative-value pressure surfaced

## 3. Anchor Mismatch

Cash Treasury, futures, funding, and liquidation anchors diverged under stress.

## 4. Path Feasibility

Dealer balance-sheet limits and forced selling reduced feasible paths.

## 5. Shadow Accumulation

Leveraged basis positions and liquidity assumptions accumulated before the March shock.

## 6. Trigger Vs Potential

- Trigger: COVID shock and dash for cash.
- Stored potential: crowded relative-value leverage and constrained intermediation.

## 7. Data Candidates

- Treasury yields and liquidity proxies
- futures basis
- repo/funding proxies
- Fed facility usage

## 8. Relevant Benchmarks

- NFCI
- VIX
- MOVE
- funding spread controls

## 9. What This Case Supports

- path contraction
- curvature deformation
- scalar compression failure

## 10. What It Does Not Prove

- That structural diagnostics dominate all broad stress indexes out of sample.

## 11. Related Code

- `src/benchmarks/historical_replay.py`
- `src/diagnostics/structural_diagnostic.py`

## 12. Paper Usage

Use as diagnostic grounding for safe-asset path contraction.

## 13. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
