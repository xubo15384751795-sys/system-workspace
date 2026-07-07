# M_t - Anchor Mismatch

## 1. Definition

`M_t` measures divergence among valuation, accounting, funding, collateral,
policy, and liquidation anchors.

## 2. What It Is Not

- Not volatility.
- Not a spread-only stress measure.
- Not a claim that one anchor is always correct.

## 3. Mechanism

`M_t` rises when actors must translate positions across anchors that no longer
agree, especially when liquidation or funding anchors force recognition of
losses that accounting or policy anchors delayed.

## 4. Observable Traces

- basis spread widening
- HTM/AOCI gaps
- funding versus fair-value divergence
- collateral haircut repricing

## 5. Benchmark Controls

- credit spread controls
- NFCI/STLFSI/OFR FSI as benchmark surfaces
- rate volatility controls

## 6. Rejection Gate

If `M_proxy` has no incremental value beyond spread and broad stress benchmarks,
the anchor-mismatch interpretation is weakened.

## 7. Related Cases

- [2023 SVB](../cases/2023_SVB.md)
- [2015 CHF peg break](../cases/2015_CHF_peg_break.md)

## 8. Related Code

- `src/proxies/m_anchor_mismatch.py`
- `src/diagnostics/residualization.py`

## 9. Paper Usage

Core diagnostic channel. Do not claim direct observation of all anchors.

## 10. Claim Discipline

Use the [Claim Registry](../claims/claim_registry.md) before paper-facing use.
