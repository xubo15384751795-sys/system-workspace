# Channel Confidence Report

**Generated:** 2026-06-02

---

## Per-Channel Confidence Assessment

| Channel | Status | Confidence | Proxy Quality | Family | Semantic Distance | Voting Proxies | Canonical Section |
|---------|--------|------------|---------------|--------|-------------------|----------------|-------------------|
| M | live | **low** | PROXY_REDUCED | FRED_RATES | 3 | 4 | §4.2 + §7.2.4 |
| D | live | **low** | PROXY_REDUCED | FRED_FUNDING | 3 | 4 | §4.3 + §7.2.1 |
| K | live | **low** | PROXY_REDUCED | CBOE_OPTIONS | 3 | 3 | §4.4 + §7.2.2 |
| X_agg | live | **low** | PROXY_REDUCED | SEC_OBS + OFR_SYSTEMIC | 3 | 2 | §4.5 + §7.2.3 |

---

## Confidence Definitions

| Level | Meaning |
|-------|---------|
| **high** | Canonical proxy, semantic_distance ≤ 1, multi-family, no warnings |
| **medium** | Reduced proxy, semantic_distance = 2, or monoculture with no warnings |
| **low** | PROXY_REDUCED, semantic_distance ≥ 3, or has governance warnings |
| **not_implemented** | Channel has no canonical_voting proxies |

---

## Why All Channels Are LOW

All 4 channels are currently **PROXY_REDUCED** with **semantic_distance = 3**. This means:

- The proxies measure something *related to* the canonical concept, but are not the canonical measurement themselves
- Example: M uses NFCI (financial conditions index) as a proxy for anchor mismatch (Δ_M), but NFCI is a broad composite, not a direct anchor-gap measure
- Example: K uses VIX term structure butterfly as a proxy for transition curvature, but this is a vol-surface measure, not a direct regime-transition measure

**To improve confidence:** Replace PROXY_REDUCED proxies with canonical measurements (e.g., direct funding-anchor gaps for M, OTM options chain data for K).

---

## Family Diversity

| Channel | Family | Diversity | Risk |
|---------|--------|-----------|------|
| M | FRED_RATES | monoculture | All M proxies come from FRED rate series — correlated by construction |
| D | FRED_FUNDING | monoculture | All D proxies come from FRED funding series |
| K | CBOE_OPTIONS | monoculture | All K proxies come from CBOE volatility series |
| X_agg | SEC_OBS + OFR_SYSTEMIC | **multi-family** | X_agg spans SEC and OFR data — better diversity |

X_agg is the only channel with multi-family diversity. This is a structural advantage.

---

## Governance Warnings

All channels carry `PROXY_REDUCED distance=3` warnings. No other governance violations detected.

---

## Recommendations

1. **Accept LOW confidence as current state.** The system is ACTIVE_FULL but all channels are PROXY_REDUCED. This is honest — the proxies are the best available data, not the canonical measurements.
2. **Priority improvement path:** K > X_agg > M > D. K has the most room for improvement (options chain data would dramatically reduce semantic distance).
3. **Do not upgrade confidence prematurely.** Confidence should only increase when proxy quality improves, not when more proxies are added.
