# X_agg Frequency & Alias Report

**Date:** 2026-06-03
**Sprint:** X Frequency & Alias Sprint

---

## Current X_agg State

| Sub-basket | Proxy | Raw Series | Frequency | Status |
|------------|-------|-----------|-----------|--------|
| v1 off_balance_sheet | X_agg_off_balance_sheet_v1 | SEC:OBS_DERIV_TO_ASSETS | **quarterly** | canonical_voting |
| v2 hidden_leverage | X_agg_hidden_leverage_ofr | OFR_FSI | daily | canonical_voting (auxiliary) |
| v2 hidden_leverage | X_agg_v2_nfcileverage_quarantined | FRED:NFCILEVERAGE | weekly | quarantined_drift |
| v3 shadow_funding | X_agg_canonical_NOT_IMPLEMENTED_v3 | (none) | weekly | awaiting_data |

**Problem:** v1 is quarterly → X_agg changes value only when new SEC filings arrive. Between filings, X_agg holds its last z-score (stale but stable). v3 has zero data.

---

## Available Harvester Series Not Yet Mapped to X_agg

### H41 (weekly) — Fed lending facilities

| Series | Currently wired to | Could map to X_agg sub-basket |
|--------|-------------------|-------------------------------|
| H41:primary_credit | X_REALIZED (diagnostic_only) + Pi_t | v2 hidden_leverage |
| H41:discount_window | X_REALIZED (diagnostic_only) + Pi_t | v2 hidden_leverage |
| H41:btfp | X_REALIZED (diagnostic_only) + Pi_t | v2 hidden_leverage |

**Mapping rationale:** Fed lending facility usage is a direct signal of systemic leverage stress. When primary credit / discount window / BTFP usage spikes, it indicates banks are under funding pressure — a form of hidden leverage. These are weekly data, better temporal precision than quarterly SEC.

**Constraint:** These series are already wired to X_REALIZED (diagnostic_only) and Pi_t. Adding them to X_agg would create cross-channel sharing. Need to verify independence vs M/D/K.

### TREASURY (daily) — Government finance

| Series | Currently wired to | Could map to X_agg sub-basket |
|--------|-------------------|-------------------------------|
| TREASURY:debt_to_penny:tot_pub_debt_out_amt | NOT WIRED | v1 off_balance_sheet (refinancing pressure) |
| TREASURY:daily_treasury_statement:open_today_bal | NOT WIRED | v2 hidden_leverage (Treasury cash balance) |

**Mapping rationale:** Total public debt outstanding is a measure of government refinancing pressure — when debt grows faster than GDP, it creates off-balance-sheet pressure. Treasury cash balance indicates fiscal stress.

**Constraint:** These are daily series — much better temporal precision than quarterly SEC. But they measure government finance, not private shadow leverage.

### FRED (daily/weekly) — Rates and stress

| Series | Currently wired to | Could map to X_agg sub-basket |
|--------|-------------------|-------------------------------|
| FRED:STLFSI4 | D_stlfsi (D channel) | v2 hidden_leverage (St. Louis FSI) |
| FRED:SOFR | D_sofr_iorb_gap, D_sofr_ff_gap (D channel) | v3 shadow_funding |
| FRED:IORB | D_sofr_iorb_gap (D channel) | v3 shadow_funding |

**Constraint:** All already wired to D channel. Mapping to X_agg would create cross-channel sharing.

### DERIVED (daily)

| Series | Currently wired to | Could map to X_agg sub-basket |
|--------|-------------------|-------------------------------|
| DERIVED:SOFR_IORB_SPREAD | NOT WIRED | v3 shadow_funding |

**Mapping rationale:** SOFR-IORB spread is a direct measure of secured funding market stress. When SOFR > IORB, money market funds have incentive to drain reserves — a shadow funding mechanism.

---

## Frequency Alignment Assessment

### Current X_agg temporal precision

| Sub-basket | Proxy freq | Effective X_agg update freq | Precision |
|------------|-----------|---------------------------|-----------|
| v1 off_balance_sheet | quarterly | **quarterly** (SEC filing cycle) | LOW |
| v2 hidden_leverage | daily | daily (OFR FSI) | HIGH |
| v3 shadow_funding | (no data) | never | NONE |

**X_agg effective update:** When only v1 has data → quarterly. When v1 + v2 both have data → daily (v2 dominates temporal resolution).

### After Sprint 4 mapping (if H41 added to v2)

| Sub-basket | Proxy freq | Effective update | Precision |
|------------|-----------|-----------------|-----------|
| v1 off_balance_sheet | quarterly | quarterly | LOW |
| v2 hidden_leverage | daily + weekly | daily (OFR FSI dominates) | HIGH |
| v3 shadow_funding | (still no data) | never | NONE |

**Net effect:** X_agg temporal precision improves from quarterly to daily because v2 (OFR FSI, daily) already provides daily updates. Adding H41 (weekly) to v2 adds coverage but doesn't change temporal precision.

---

## Mapping Recommendations

### Tier 1: Safe to map (no cross-channel conflict)

| Series | Target sub-basket | Rationale |
|--------|------------------|-----------|
| TREASURY:debt_to_penny:tot_pub_debt_out_amt | v1 off_balance_sheet | Government refinancing pressure, daily, not used by M/D/K |
| TREASURY:daily_treasury_statement:open_today_bal | v2 hidden_leverage | Treasury cash balance, daily, not used by M/D/K |
| DERIVED:SOFR_IORB_SPREAD | v3 shadow_funding | Secured funding stress, daily, not used by M/D/K |

### Tier 2: Needs independence check (already wired to other channels)

| Series | Current channel | Target sub-basket | Risk |
|--------|----------------|------------------|------|
| H41:primary_credit | X_REALIZED + Pi_t | v2 hidden_leverage | Cross-channel sharing |
| H41:discount_window | X_REALIZED + Pi_t | v2 hidden_leverage | Cross-channel sharing |
| H41:btfp | X_REALIZED + Pi_t | v2 hidden_leverage | Cross-channel sharing |
| FRED:STLFSI4 | D channel | v2 hidden_leverage | Cross-channel sharing |

### Tier 3: Not recommended

| Series | Reason |
|--------|--------|
| FRED:SOFR | Already core to D channel |
| FRED:IORB | Already core to D channel |
| FRED:NFCILEVERAGE | Broad composite forbidden for X_agg |
| SEC:0000072971 | CIK identifier, not a financial metric |

---

## Temporal Precision Summary

| Metric | Before Sprint 4 | After Tier 1 mapping |
|--------|----------------|---------------------|
| X_agg effective frequency | quarterly (v1 only) | daily (v2 OFR FSI) |
| X_agg sub-basket coverage | 1/3 (v1 only) | 2/3 (v1 + v2 + partial v3) |
| Daily updates available | Yes (via v2 OFR FSI) | Yes |
| Quarterly stale periods | Yes (v1 SEC filings) | Still present in v1 |

**Key insight:** X_agg already has daily temporal precision through v2 (OFR FSI). The quarterly problem is only in v1 (SEC). Adding Tier 1 series improves coverage, not temporal precision.

---

## Next Steps

1. **Tier 1 mapping:** Wire TREASURY:debt_to_penny and DERIVED:SOFR_IORB_SPREAD to X_agg sub-baskets
2. **Independence check:** Verify H41 series don't share raw data with M/D/K
3. **v3 activation:** DERIVED:SOFR_IORB_SPREAD could be the first v3 proxy
4. **No new proxy definitions needed:** Use existing proxy patterns in structural_replay_v2.py
