# A_t - Anchor Configuration

## 1. Definition

`A_t` represents the valuation, accounting, funding, collateral, and policy
anchors that actors use to judge feasibility and loss realization.

## 2. What It Is Not

- Not a single fair value.
- Not only accounting book value.
- Not only monetary policy.

## 3. Mechanism

Anchor mismatch rises when actors are forced to move between incompatible
reference systems such as book value, fair value, funding value, and liquidation value.

## 4. Observable Traces

- HTM/AOCI gaps
- basis spreads
- collateral haircut changes
- policy path repricing

## 5. Benchmark Controls

- credit spreads
- funding spreads
- rate volatility

## 6. Rejection Gate

If anchor-gap proxies collapse into ordinary spread or volatility measures, the
anchor interpretation is weakened.

## 7. Related Cases

- [2023 SVB](../cases/2023_SVB.md)
- [2015 CHF peg break](../cases/2015_CHF_peg_break.md)

## 8. Related Code

- `src/proxies/m_anchor_mismatch.py`
- `src/derivation/proxy_builder.py`

## 9. Paper Usage

Use to motivate `M_t` anchor mismatch and forced realization mechanisms.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
