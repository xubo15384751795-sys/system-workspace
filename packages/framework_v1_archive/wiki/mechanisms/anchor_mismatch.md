# Anchor Mismatch

## 1. Definition

Anchor mismatch occurs when accounting, funding, collateral, market, policy, or
liquidation anchors no longer support the same state interpretation.

## 2. Structural Role

It raises `M_t` and can force transitions from latent mismatch to realized loss.

## 3. Observable Traces

- book-to-market divergence
- basis spread widening
- collateral haircut repricing
- policy path repricing

## 4. Cases

- [2023 SVB](../cases/2023_SVB.md)
- [2015 CHF peg break](../cases/2015_CHF_peg_break.md)

## 5. Rejection Gate

If anchor-mismatch proxies are absorbed by ordinary spread controls, the
mechanism should be weakened.

## 6. Related Code

- `src/proxies/m_anchor_mismatch.py`

## 7. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
