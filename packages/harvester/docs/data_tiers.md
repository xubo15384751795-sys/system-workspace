# Fast-Track Data Tiers

This is the Harvester position on data freshness for fast-track daily structural diagnostics.

The fast track needs tier 2 and tier 3 data. It does not need tier 4 streaming unless a separate high-frequency trading use case is approved.

| Tier | Freshness | Providers | Purpose | Status |
| --- | --- | --- | --- | --- |
| 1 | T+1 | FRED | Macro, rates, and credit-spread anchors such as DFF, T10Y2Y, SOFR, DAAA, DBAA, NFCI. | Admitted |
| 2 | Same-day EOD | CBOE direct CSV, OpenBB/Tiingo | Volatility term structure and ETF liquidity/depth inputs: VVIX, SKEW, TYVIX, VIX3M, VIX9D, HYG, LQD, TLT. | Admitted |
| 3 | Intraday delayed | CBOE delayed JSON | Market-hours polling for VIX, VVIX, and SKEW, approximately 15 minutes delayed. | Admitted |
| 4 | True streaming | Massive or another commercial WebSocket provider | High-frequency push feeds. | Not required |

## Coverage

Current admitted coverage:

| Signal | Freshness | Source | Harvester provider |
| --- | --- | --- | --- |
| VIX / VVIX / SKEW | Intraday delayed | CBOE JSON | `cboe_direct` |
| VIX3M / VIX9D / TYVIX | Same-day EOD | CBOE CSV | `cboe_direct` |
| DFF / T10Y2Y / SOFR | T+1 | FRED | `fred`, `openbb_fred` fallback |
| Credit spreads / yields | T+1 | FRED | `fred`, `openbb_fred` fallback |
| HYG / LQD / TLT prices | Same-day EOD | Tiingo through OpenBB | `openbb_tiingo` |

## Operating Rule

Daily structural-risk diagnostics should prefer stable public/EOD data over streaming infrastructure. Streaming feeds are explicitly out of scope for the fast track because the diagnostic target is multi-day structural pressure, not sub-second execution.

Machine-readable policy lives in `configs/data_tiers.yaml`.
