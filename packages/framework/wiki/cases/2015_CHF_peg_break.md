# 2015 CHF Peg Break - Policy Anchor Repricing

## 1. Event Summary

On 2015-01-15, the Swiss National Bank discontinued the EUR/CHF floor, causing a
sharp repricing of currency and related positions.

## 2. Structural Diagnosis

- `M`: high, policy anchor broke relative to market anchor
- `D`: impaired, stop-loss and liquidity paths narrowed
- `K`: high, transition map changed discontinuously
- `X`: moderate, hidden exposure depended on positioning

## 3. Anchor Mismatch

The policy floor anchor diverged from the market-clearing anchor once the peg was removed.

## 4. Path Feasibility

Liquidity and execution paths contracted during the repricing window.

## 5. Shadow Accumulation

Positioning built around a stable policy anchor before realization.

## 6. Trigger Vs Potential

- Trigger: SNB policy announcement.
- Stored potential: one-way positioning and anchor reliance.

## 7. Data Candidates

- FX spot data
- FX volatility
- broker and fund commentary as corpus context

## 8. Relevant Benchmarks

- FX volatility controls
- MOVE/VIX as broad volatility context

## 9. What This Case Supports

- anchor mismatch
- curvature deformation
- path contraction

## 10. What It Does Not Prove

- General policy-peg break prediction.

## 11. Related Code

- `src/proxies/m_anchor_mismatch.py`
- `src/proxies/k_transition_deformation.py`

## 12. Paper Usage

Use as an anchor-break example with cautious data language.

## 13. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
