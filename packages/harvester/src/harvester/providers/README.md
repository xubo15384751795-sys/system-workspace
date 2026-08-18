# Providers

A provider knows how to acquire one or more upstream series and normalize them
into Harvester's provider result shape. Release staging is responsible for
writing the final data files, manifests, and provenance records.

Implemented providers include:

- `fred`: FRED observations API.
- `h41`: direct Federal Reserve H.4.1 Data Download Program CSV, with FRED
  bridge fallback when configured.
- `treasury`: U.S. Treasury FiscalData APIs.
- `sec`: SEC EDGAR filing pulse.
- `cboe_direct`: CBOE direct public CSV and delayed JSON endpoints.
- `etf_market_data`: Tiingo -> Massive (formerly Polygon.io) -> yfinance ETF
  provider chain with per-provider cooldown, cache, and source provenance.
- `openbb_provider`: OpenBB-backed routes for FRED, Tiingo, and selected market
  data.
- `external_indicators`: public-file indicators such as OFR FSI.

## Boundary Rules

Providers may write raw bytes under `data/raw/<provider>/...` and
intermediates under `data/processed/<provider>/...`. Those paths are internal
working storage and are not part of the access protocol.

Consumer-visible data must be promoted into `data/exports/<release_id>/` with:

- one declared data file under `data/`
- one manifest under `manifests/`
- one provenance record under `provenance/`
- optional quality reports under `quality_reports/`

Providers must not mutate finalized releases. Corrections go into a new release.
Cross-provider dependencies should use manifested upstream release artifacts,
not another provider's raw or processed workspace.
