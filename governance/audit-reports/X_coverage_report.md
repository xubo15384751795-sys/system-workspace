# X_agg MVP Coverage Report

**Generated:** 2026-06-02
**Panel:** Harvester 2026-06-02-r8 `benchmark_panel.parquet`
**Proxy definitions:** `Structural Deformation Research System/src/proxies/x_shadow_accumulation.py`
**Proxy builder:** `Structural Deformation Research System/src/derivation/proxy_builder.py`

---

## Summary

| Metric | Value |
|--------|-------|
| Total X proxy inputs defined | 31 |
| Inputs with raw series available | 5 |
| Inputs missing raw series | 26 |
| **Coverage** | **16.1%** |
| P0 inputs available | 3 / 3 (100%) |
| P1 inputs available | N/A (3 series available in panel, not yet mapped to proxy inputs) |
| P2 inputs available | 0 / 28 (0%) |

The Harvester panel contains all high-priority raw series needed for MVP connection. The 26 missing inputs are synthetic proxy IDs (prefixed `X_`) that would require new Harvester series definitions or derived computation. One additional input (`X_OBS_ASSETS`) has a semantic match to `OBS_DERIV_TO_ASSETS` in the panel but the ID mismatch prevents automatic connection.

---

## Cross-Reference: Proxy Inputs vs. Available Raw Series

### X_REALIZED channel — X_OFFICIAL_SUPPORT_USAGE group

| proxy_input_id | raw_series_available | status | priority |
|---|---|---|---|
| `primary_credit` | `primary_credit` (H41, weekly, mil_usd) | **available** | P0 |
| `discount_window` | `discount_window` (H41, weekly, mil_usd) | **available** | P0 |
| `btfp` | `btfp` (H41, weekly, mil_usd) | **available** | P0 |
| `X_PRIMARY_CREDIT` | — | missing | P2 |
| `X_DISCOUNT_WINDOW` | — | missing | P2 |
| `X_BTFP` | — | missing | P2 |
| `X_OFFICIAL_SUPPORT_USAGE` | — | missing | P2 |

### X_REALIZED channel — X_SUPPORT_SUBSTITUTION group

| proxy_input_id | raw_series_available | status | priority |
|---|---|---|---|
| `X_SUPPORT_SUBSTITUTION` | — | missing | P2 |
| `X_FED_LIQUIDITY_FACILITY_USAGE` | — | missing | P2 |
| `X_EMERGENCY_LIQUIDITY_USAGE` | — | missing | P2 |

### X_PRE channel — X_HIDDEN_LEVERAGE group

| proxy_input_id | raw_series_available | status | priority |
|---|---|---|---|
| `X_HIDDEN_LEVERAGE` | — | missing | P2 |
| `X_MARGIN_DEBT` | — | missing | P2 |
| `X_DEALER_LEVERAGE_PROXY` | — | missing | P2 |
| `X_BROKER_DEALER_ASSETS` | — | missing | P2 |
| `X_REPO_VOLUME_COLLATERAL_REUSE` | — | missing | P2 |
| `X_OBS_ASSETS` | `OBS_DERIV_TO_ASSETS` (SEC, quarterly, ratio) — **semantic match only, ID mismatch** | missing (remap needed) | P2 |

### X_PRE channel — X_SHADOW_SUBSTITUTION group

| proxy_input_id | raw_series_available | status | priority |
|---|---|---|---|
| `X_SHADOW_SUBSTITUTION` | — | missing | P2 |
| `X_SHADOW_FUNDING` | — | missing | P2 |
| `X_PRIVATE_CREDIT_GROWTH` | — | missing | P2 |
| `X_NONBANK_LENDING_GROWTH` | — | missing | P2 |
| `X_MMF_REPO_INTERMEDIATION` | — | missing | P2 |

### X_PRE channel — X_MATURITY_MISMATCH group

| proxy_input_id | raw_series_available | status | priority |
|---|---|---|---|
| `X_MATURITY_MISMATCH` | — | missing | P2 |
| `X_SHORT_TERM_FUNDING_RELIANCE` | — | missing | P2 |
| `X_MATURITY_WALL` | — | missing | P2 |
| `X_DEPOSIT_BETA_UNINSURED_STRESS` | — | missing | P2 |
| `X_ASSET_LIABILITY_DURATION_MISMATCH` | — | missing | P2 |

### X_PRE channel — X_VALUATION_LAG group

| proxy_input_id | raw_series_available | status | priority |
|---|---|---|---|
| `X_VALUATION_LAG` | — | missing | P2 |
| `X_PRIVATE_ASSET_VALUATION_LAG` | — | missing | P2 |
| `X_HTM_UNREALIZED_LOSS_PROXY` | — | missing | P2 |
| `X_CRE_STALE_MARKS` | — | missing | P2 |
| `X_PRIVATE_CREDIT_STALE_MARKS` | — | missing | P2 |

---

## Additional Panel Series Available for X_agg

The following benchmark panel series are not currently referenced by any X proxy input but are candidates for future X_agg connection:

| series_id | source | frequency | potential X group |
|---|---|---|---|
| `tot_pub_debt_out_amt` | treasury | daily | X_MATURITY_MISMATCH (refinancing pressure) |
| `open_today_bal` | treasury | daily | X_OFFICIAL_SUPPORT_USAGE (treasury cash balance) |
| `SEC_FILING_PULSE` | sec | daily | X_VALUATION_LAG (filing distress signal) |
| `NFCILEVERAGE` | fred | weekly | X_HIDDEN_LEVERAGE (leverage subindex) |
| `NFCICREDIT` | fred | weekly | X_SHADOW_SUBSTITUTION (credit subindex) |
| `SOFR` | fred | daily | X_SHADOW_FUNDING (secured rate stress) |
| `IORB` | fred | daily | X_OFFICIAL_SUPPORT_USAGE (reserve rate) |
| `OFR_FSI` | ofr | daily | X_HIDDEN_LEVERAGE (systemic stress) |

---

## Priority Definitions

| Priority | Definition | Inputs |
|---|---|---|
| **P0** | Core H41 official support data — direct Federal Reserve DDP CSV. Must-connect for MVP X_REALIZED. | `primary_credit`, `discount_window`, `btfp` |
| **P1** | Treasury and SEC raw series available in panel but not yet mapped to proxy inputs (`tot_pub_debt_out_amt`, `open_today_bal`, `SEC_FILING_PULSE`, `OBS_DERIV_TO_ASSETS`). Require new proxy input definitions or remapping. | No proxy inputs defined yet |
| **P2** | Treasury, SEC panel series (not yet mapped to proxy inputs), and all `X_`-prefixed synthetic proxies. Require new Harvester series, derived computation, or external data acquisition. | 28 inputs (all `X_`-prefixed) |

---

## Proxy Builder Connection Path

The `DefaultProxyBuilder` consumes a wide-format DataFrame where:
- Column names = `series_id` values from the benchmark panel
- The builder's `_basket_score()` method looks for `spec["id"]` as a column name
- Z-score normalization uses a 260-week rolling window with ±3σ winsorization

For the 3 available P0 inputs, connection requires:
1. The benchmark panel (long format: `date`, `series_id`, `value`) must be pivoted to wide format
2. The basket map for `X_PRE` and `X_REALIZED` channels must include specs with `id` matching the available `series_id` values
3. Currently the basket map is built from `x_shadow_accumulation.py` definitions where `ProxyInput.id` is used as the builder spec `id`

**Critical mismatch:** The 3 P0 inputs (`primary_credit`, `discount_window`, `btfp`) use bare names that match the H41 series registry canonical IDs. However, they are currently nested inside the `X_OFFICIAL_SUPPORT_USAGE` group alongside 4 missing `X_`-prefixed inputs. The proxy builder will compute a basket score using only the 3 available inputs (mean of 3 z-scores), ignoring the 4 missing ones — this is correct fallback behavior.

---

## Recommended Next Steps

1. **Connect P0 inputs immediately** — the `X_REALIZED/X_OFFICIAL_SUPPORT_USAGE` group can produce a basket score from `primary_credit`, `discount_window`, `btfp` with 3/7 inputs (43% group coverage)
2. **Add Treasury series to X_PRE groups** — `tot_pub_debt_out_amt` → X_MATURITY_MISMATCH; `open_today_bal` → X_OFFICIAL_SUPPORT_USAGE
3. **Map `SEC_FILING_PULSE`** to X_VALUATION_LAG as a verifiability signal
4. **Define Harvester series** for the 19 remaining `X_`-prefixed inputs that have no panel data and no obvious proxy (margin debt, dealer leverage, private credit growth, etc.)
5. **Consider `NFCILEVERAGE`** as a bridge for X_HIDDEN_LEVERAGE until direct margin-debt data is acquired
