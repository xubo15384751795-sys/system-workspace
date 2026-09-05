# Legacy Acquisition Inventory And Cutover Plan

Status: inventory only. Do not move code from this document.

Boundary principle:

```text
Framework does not fetch the world.
Framework consumes admitted evidence.
```

## Category Legend

- A: migrate to Harvester provider/acquisition layer
- B: keep in Deformation as admitted-evidence -> structural-input transform
- C: move to tests/fixtures or mock utilities
- D: keep temporarily as deprecated compatibility shim

## Inspected Legacy-Allowed Modules

The current guard allow-list in `tests/test_data_boundary.py` covers:

- `src/data/data_sources.py`
- `src/data/adapters/__init__.py`
- `src/data/adapters/public_adapters.py`
- `src/data/gateway/bridge.py`
- `src/data/gateway/data_hub.py`
- `src/data/external_downloads.py`
- `src/benchmarks/historical_replay.py`
- `src/research_corpus/providers/brevan_howard.py`

## Import Graph

| Legacy module | Current importers / callers | Importer type | Notes |
|---|---|---|---|
| `src.data.data_sources` | `src/data/adapters/public_adapters.py`, `src/data/gateway/data_hub.py`, `src/data/gateway/bridge.py` | legacy provider/gateway | Core acquisition dependency chain. |
| `src.data.data_sources` | `scripts/benchmark_data_capture.py` | script | Direct FRED acquisition script. |
| `src.data.data_sources` | `tests/test_data_ingestion_fred.py`, `tests/test_data_source_selection.py`, `tests/test_pipeline_integration.py`, `tests/test_proxy_builder.py`, `tests/test_singular_detector.py`, `tests/test_ode_engine.py`, `tests/test_ml_anomaly.py` | tests | Mostly mock/FRED compatibility tests. |
| `src.data.adapters.public_adapters` | `src/data/adapters/__init__.py` | compatibility re-export | Keeps adapter names available through `src.data.adapters`. |
| `src.data.adapters` | `src/data/gateway/data_hub.py`, `tests/test_data_hub.py` | gateway/tests | DataHub imports provider adapters from package re-export. |
| `src.data.gateway.data_hub` | `src/data/gateway/__init__.py` | compatibility re-export | Public gateway package exposes `DataHub` and `create_data_hub`. |
| `src.data.gateway.bridge` | `src/data/gateway/__init__.py` | compatibility re-export | Public gateway package exposes `DataHubBridge`. |
| `src.data.external_downloads` | `scripts/fetch_full_benchmark_panel.py` | script | Former blocker. Phase A replaced the script with a deprecated fail wrapper; it no longer imports `src.data.external_downloads`. |
| `src.data.external_downloads` | `tests/test_external_downloads.py` | tests | Compatibility tests now assert the Deformation wrapper fails closed. |
| `src.benchmarks.historical_replay` | `scripts/run_allocation_backtest.py`, `scripts/run_information_tests.py`, `scripts/fetch_full_benchmark_panel.py`, `src/benchmarks/__init__.py`, `src/benchmarks/public_baselines.py` | scripts/framework benchmark | Mixed: FRED acquisition plus structural backtest transforms. |
| `src.research_corpus.providers.brevan_howard` | `src/research_corpus/providers/__init__.py`, `tests/test_research_corpus.py` | research-corpus provider/tests | Acquisition is narrative corpus, not market data, but still external fetching. |

Importer classification:

- Tests: safe to preserve with mock/fixture replacements.
- Scripts: migration blockers if they are still user-facing.
- UI/dashboard: no direct imports found for the inspected modules except via runtime/gateway objects.
- Historical replay: mixed acquisition and framework benchmark logic.
- Core analysis: runtime assembly reaches legacy provider branch through `src.data.gateway` exports, `create_data_hub`, and `DataHubBridge`.

## Module Inventory

### `src/data/data_sources.py`

Module responsibility: legacy provider clients, HTTP client, mock source, composite source, proxy aggregation, and compatibility factory.

| Symbol | Lines | Current responsibility | External HTTP | API keys | Raw/cache/provider data | Importers / callers | Cat | Target location | Migration action | Priority | Risk if moved |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| `_now_perf` | 64-65 | Timing helper for legacy fetch metadata. | No | No | No | Internal only | D | Delete after shim removal | Keep until legacy clients removed. | Low | None. |
| `_elapsed_ms` | 68-69 | Timing helper. | No | No | No | Internal only | D | Delete after shim removal | Keep until legacy clients removed. | Low | None. |
| `_safe_fetch_metadata` | 72-74 | Reads provider metadata from sources. | No | No | Provider metadata only | `CompositeDataSource`, `ProxyAggregationDataSource` | D | Harvester provider result metadata or structural input builder metadata | Replace with protocol metadata reads. | Medium | Metadata regressions in reports. |
| `_provider_from_series_id` | 77-80 | Parses provider prefix from series IDs. | No | No | Provider identity | `MockDataSource` | D | Harvester provider schema / tests fixture helper | Keep only in tests if still needed. | Low | Test-only naming changes. |
| `_set_last_fetch_metadata` | 83-84 | Mutates source with legacy metadata. | No | No | Provider metadata | All provider classes | D | Harvester `ProviderResult.metadata` | Replace mutation with returned metadata. | Medium | Runtime provenance fields may change. |
| `_normalize_columns` | 87-93 | Date-index normalization for provider frames. | No | No | Provider parse output | Provider/composite/proxy classes | A | `harvester/providers/base.py` or `harvester/parsers/timeseries.py` | Move as provider parse helper. | Medium | Subtle date sorting/index behavior. |
| `_empty_result` | 96-97 | Empty DataFrame helper. | No | No | No | Provider classes | D | Delete or keep in Harvester helper | Inline or move with providers. | Low | None. |
| `_coerce_series` | 100-101 | Numeric coercion before aggregation. | No | No | No | `ProxyAggregationDataSource` | B | `src/structural_inputs/proxy_mapping.py` | Keep logic in structural input transform, fed by admitted evidence. | Medium | Proxy values may shift if coercion changes. |
| `_extract_prefixed_series_ids` | 104-114 | Provider request parsing by prefix. | No | No | Provider request mapping | Provider classes | A | Harvester provider request parser | Move with provider acquisition. | Medium | Provider request compatibility. |
| `MockDataSource` | 118-149 | Synthetic data for tests/fallback. | No | No | Synthetic only | Many tests, provider fallbacks | C | `tests/fixtures/mock_data_source.py` or `src/testing/mock_data_source.py` | Move tests to fixture; remove as provider fallback in runtime. | High | Broad test churn; fallback runtime behavior changes. |
| `HTTPClient` | 152-187 | urllib HTTP wrapper with retry/backoff. | Yes | No | Provider transport | Provider classes, public adapters, DataHub | A | Harvester `providers/base.py` | Move to Harvester; Deformation must not expose it. | High | Provider behavior changes if moved incorrectly. |
| `FREDDataSource` | 190-417 | FRED API/graph CSV acquisition, cache, fallback. | Yes | Yes, constructor receives key | FRED graph CSV cache | Scripts/tests/public adapters | A | Harvester `providers/fred.py` | Move provider logic; Deformation consumes released FRED panels only. | High | High: cache paths, fallback behavior, benchmark scripts. |
| `FederalReserveH41DataSource` | 420-556 | Fed H.4.1 CSV acquisition/parse/fallback. | Yes | No | Provider response parse | Public adapters/DataHub | A | Harvester `providers/h41.py` | Move provider logic. | High | H41 preset compatibility. |
| `SECEDGARDataSource` | 559-673 | SEC submissions acquisition and filing-count time series. | Yes | No, but user-agent config | Provider response parse | Public adapters/DataHub | A | Harvester `providers/sec.py` | Move provider logic. | High | SEC user-agent and filing semantics. |
| `TreasuryFiscalDataSource` | 676-786 | Treasury Fiscal Data API acquisition/parse. | Yes | No | Provider response parse | Public adapters/DataHub | A | Harvester `providers/treasury.py` | Move provider logic. | High | Treasury dataset request compatibility. |
| `AlphaVantageDataSource` | 789-857 | Alpha Vantage daily adjusted acquisition. | Yes | Yes, constructor receives key | Provider response parse | Public adapters/DataHub | A | Harvester `providers/alpha_vantage.py` | Move provider logic. | Medium | Optional provider; fallback behavior. |
| `PolygonDataSource` | 860-921 | Polygon aggregates acquisition. | Yes | Yes, constructor receives key | Provider response parse | Public adapters/DataHub | A | Harvester `providers/polygon.py` | Move provider logic. | Medium | Optional provider; ticker/field parsing. |
| `NasdaqDataLinkDataSource` | 924-1007 | Nasdaq Data Link dataset acquisition. | Yes | Yes, constructor receives key | Provider response parse | Public adapters/DataHub | A | Harvester `providers/nasdaq_data_link.py` | Move provider logic. | Medium | Optional provider; dataset spec parsing. |
| `CompositeDataSource` | 1010-1112 | Combines provider source outputs with fallback. | Indirect | Indirect | Provider orchestration | Legacy factory/tests | A/D | Harvester `ProviderHub` or delete | Replace with Harvester provider registry/release builder. | Medium | Combining/fallback semantics may alter old dashboards. |
| `ProxyAggregationDataSource` | 1115-1355 | Expands provider series and aggregates into M/D/K/X proxies; also maintains raw in-memory cache. | Indirect through source | Indirect | Raw in-memory provider cache | Legacy factory/tests | B/D split | `src/structural_inputs/proxy_mapping.py` and `snapshot_builder.py`; provider expansion removed | Keep aggregation math only after inputs come from `AdmittedEvidenceBundle`; remove provider expansion/cache. | High | Core proxy values may change; must golden-test. |
| `DataSourceFactory` | 1358-1371 | Compatibility factory builds `DataHubBridge` and `create_data_hub`. | Indirect | Indirect | Provider branch entrypoint | Tests/legacy callers | D | Deprecated wrapper, then removal | Point callers to `AdmittedEvidenceHub` or structural input builder. | High | Runtime assembly depends on bridge path today. |

Acquisition vs structural-input split:

- Acquisition: `HTTPClient`, all concrete provider data sources, provider prefix extraction, provider metadata/fallback orchestration, raw/cache handling.
- Structural-input transform: only the proxy math inside `ProxyAggregationDataSource` (`_coerce_series`, `_parse_component`, `_zscore`, `_aggregate_proxy`) should survive in Deformation, and only after it consumes admitted evidence panels.

### `src/data/adapters/public_adapters.py`

Module responsibility: legacy adapter layer translating typed data contracts to provider clients.

| Symbol | Lines | Current responsibility | External HTTP | API keys | Raw/cache/provider data | Importers / callers | Cat | Target location | Migration action | Priority | Risk if moved |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| `_series_result` | 52-68 | Wraps provider frames into `SeriesResult`. | No | No | Provider metadata | All series adapters | A/D | Harvester provider result adapter or compatibility shim | Replace with Harvester `ProviderResult` and Workbench evidence contract mapping. | Medium | Contract shape changes. |
| `_coerce_date` | 71-75 | Provider date normalization. | No | No | Provider parse output | Event/filing/position adapters | A | Harvester parser helper | Move with providers. | Low | Date edge cases. |
| `_best_value` | 78-82 | Pick first present provider row field. | No | No | Provider parse output | CFTC/Treasury helpers | A | Harvester parser helper | Move with providers. | Low | Field mapping behavior. |
| `MockSeriesAdapter` | 86-93 | Mock series contract adapter. | No | No | Synthetic only | `_register_mock_adapters`, tests | C | tests fixtures | Replace runtime mock branch with explicit test fixtures. | Medium | Tests using DataHub mock branch need update. |
| `MockEventAdapter` | 97-110 | Mock event adapter. | No | No | Synthetic only | `_register_mock_adapters`, tests | C | tests fixtures | Move to fixtures. | Medium | Tests. |
| `MockFilingAdapter` | 114-128 | Mock SEC filing adapter. | No | No | Synthetic only | `_register_mock_adapters`, tests | C | tests fixtures | Move to fixtures. | Medium | Tests. |
| `MockPositionAdapter` | 132-149 | Mock CFTC position adapter. | No | No | Synthetic only | `_register_mock_adapters`, tests | C | tests fixtures | Move to fixtures. | Medium | Tests. |
| `FREDSeriesAdapter` | 153-174 | Typed contract adapter over `FREDDataSource`. | Yes via source | Yes | FRED cache via source | DataHub | A | Harvester `providers/fred.py` | Merge into Harvester provider API. | High | Most-used public data path. |
| `FedH41SeriesAdapter` | 178-197 | Typed adapter over H41 data source. | Yes via source | No | Provider parse | DataHub | A | Harvester `providers/h41.py` | Merge into Harvester provider API. | High | H41 structural presets. |
| `TreasurySeriesAdapter` | 201-223 | Treasury series adapter. | Yes via source | No | Provider parse | DataHub | A | Harvester `providers/treasury.py` | Merge into Harvester provider API. | High | Treasury datasets. |
| `TreasuryEventAdapter` | 227-269 | Treasury event acquisition from Fiscal Data. | Yes | No | Provider response parse | DataHub | A | Harvester `providers/treasury.py` | Move as event-capable provider. | Medium | Event contract shape. |
| `SECSeriesAdapter` | 273-290 | SEC filing-count series adapter. | Yes via source | No | Provider parse | DataHub | A | Harvester `providers/sec.py` | Merge into Harvester provider API. | High | SEC preset output. |
| `SECFilingAdapter` | 294-347 | SEC filing list acquisition. | Yes | No | Provider response parse | DataHub | A | Harvester `providers/sec.py` | Move as filing provider. | Medium | Filing URL/facts metadata. |
| `ECBSeriesAdapter` | 351-386 | ECB SDMX CSV acquisition/parse. | Yes | No | Provider parse | DataHub | A | Harvester `providers/ecb.py` | Move provider logic. | Medium | CSV schema variations. |
| `CFTCPositionAdapter` | 390-449 | CFTC Socrata JSON acquisition/parse. | Yes | No | Provider parse | DataHub | A | Harvester `providers/cftc.py` | Move provider logic. | Medium | Field candidate mapping. |
| `AlphaVantageSeriesAdapter` | 453-469 | Alpha Vantage typed adapter. | Yes via source | Yes | Provider parse | DataHub | A | Harvester `providers/alpha_vantage.py` | Move provider logic. | Medium | Optional provider. |
| `PolygonSeriesAdapter` | 473-489 | Polygon typed adapter. | Yes via source | Yes | Provider parse | DataHub | A | Harvester `providers/polygon.py` | Move provider logic. | Medium | Optional provider. |
| `NasdaqDataLinkSeriesAdapter` | 493-510 | Nasdaq Data Link typed adapter. | Yes via source | Yes | Provider parse | DataHub | A | Harvester `providers/nasdaq_data_link.py` | Move provider logic. | Medium | Optional provider. |
| `StooqSeriesAdapter` | 514-531 | Stooq CSV acquisition/parse. | Yes | No | Provider parse | DataHub | A | Harvester `providers/stooq.py` | Move provider logic. | Low | Mostly optional. |
| `TiingoSeriesAdapter` | 535-557 | Tiingo acquisition/parse. | Yes | Yes | Provider parse | DataHub | A | Harvester `providers/tiingo.py` | Move provider logic. | Medium | Optional provider/API token. |
| `CBOESeriesAdapter` | 561-585 | CBOE VIX history CSV acquisition/parse. | Yes | No | Provider parse | DataHub | A | Harvester `providers/cboe.py` | Move provider logic. | Medium | Benchmark evidence path. |
| `GenericCSVSeriesAdapter` | 589-611 | Generic CSV provider adapter for OECD/BIS/FFIEC. | Yes | No | Provider parse | DataHub | A | Harvester generic CSV provider/parser | Move provider logic with explicit admission policy. | Medium | Too generic; needs stricter Harvester config. |
| `IMFSeriesAdapter` | 615-633 | IMF SDMX JSON acquisition/parse. | Yes | No | Provider parse | DataHub | A | Harvester `providers/imf.py` | Move provider logic. | Medium | Nested JSON parsing. |
| `_json_rows_date_value_frame` | 655-671 | JSON row date/value parser. | No | No | Provider parse output | Tiingo adapter | A | Harvester parser helper | Move with providers. | Low | JSON schema behavior. |
| `_request_url` | 674-682 | Builds generic provider URLs. | No | No | Provider request construction | Generic/IMF adapters | A | Harvester provider request builder | Move and constrain. | Medium | Generic URL construction can hide new sources. |
| `_metadata_tuple` | 685-691 | Metadata list normalization. | No | No | Provider parser config | Generic adapters | A | Harvester parser helper | Move with providers. | Low | None. |
| `_extract_imf_observations` | 694-710 | IMF response parser. | No | No | Provider parse output | IMF adapter | A | Harvester `providers/imf.py` | Move with IMF provider. | Low | IMF schema edge cases. |
| `_to_float` | 713-715 | Numeric parser. | No | No | Provider parse output | CFTC adapter | A | Harvester parser helper | Move with providers. | Low | None. |

### `src/data/adapters/__init__.py`

Module responsibility: compatibility re-export only.

No classes/functions are defined. The module imports and re-exports every public adapter from `public_adapters.py`.

| Symbol | Lines | Current responsibility | External HTTP | API keys | Raw/cache/provider data | Importers / callers | Cat | Target location | Migration action | Priority | Risk if moved |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| module re-export | 1-53 | Re-exports legacy provider adapters. | Indirect | Indirect | Indirect | `src/data/gateway/data_hub.py`, tests | D | Deprecated shim | Stop re-exporting provider adapters after DataHub provider branch is replaced. | Medium | Breaks imports from `src.data.adapters`. |

### `src/data/gateway/data_hub.py`

Module responsibility: mixed provider registry, auth/env key reading, normalized fetch contracts, structural preset routing.

| Symbol | Lines | Current responsibility | External HTTP | API keys | Raw/cache/provider data | Importers / callers | Cat | Target location | Migration action | Priority | Risk if moved |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| `DataHub` | 69-291 | Routes typed requests to registered provider adapters; also enforces structural preset metadata. | Indirect | Indirect | Provider registry | Runtime assembly, API, UI via package exports | D/B split | `Harvester ProviderHub` for provider registry; Deformation `structural_inputs` for preset-to-proxy mapping | Split: provider routing to Harvester; keep only admitted-evidence mapping semantics in Deformation. | High | Runtime assembly and API currently expect this object. |
| `create_data_hub` | 294-461 | Constructs provider clients, reads env/API keys, creates HTTP client, registers providers. | Indirect | Yes: FRED, Alpha Vantage, Tiingo, Polygon, Nasdaq Data Link; SEC user-agent | Provider registry/cache config | Runtime assembly, scripts, tests | A/D | Harvester `providers/provider_hub.py`; Deformation fail/deprecated wrapper | First replace provider branch with explicit error; use Harvester releases for Deformation. | Critical | Biggest boundary violation; direct runtime dependency. |
| `_register_mock_adapters` | 464-482 | Registers mock adapters for DataHub tests/runtime mock mode. | No | No | Synthetic | `create_data_hub(use_mock=True)` | C/D | tests fixtures | Keep until tests move off DataHub; then remove. | Medium | Test churn. |
| `_missing_provider` | 485-486 | Builds typed missing-provider error. | No | No | No | `DataHub` methods | D | Delete with DataHub provider branch | Keep while DataHub exists. | Low | None. |

### `src/data/gateway/bridge.py`

Module responsibility: legacy runtime bridge from DataHub structural presets to M/D/K/X proxy frame.

| Symbol | Lines | Current responsibility | External HTTP | API keys | Raw/cache/provider data | Importers / callers | Cat | Target location | Migration action | Priority | Risk if moved |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| `DataHubBridge` | 25-213 | Calls DataHub, records evidence manifest, aggregates preset components into proxies. | Indirect via hub | Indirect via hub | Provider-shaped component frames | Runtime assembly via `src.data.gateway` | B/D split | `src/structural_inputs/snapshot_builder.py` and `proxy_mapping.py` | Replace hub fetch with `AdmittedEvidenceBundle` panel read; keep aggregation/manifest logic where framework-specific. | High | Current pipeline fetch path. |
| `_parse_component` | 220-256 | Parses proxy component specs with weights/inversion. | No | No | No | `DataHubBridge`; similar logic in `ProxyAggregationDataSource` | B | `src/structural_inputs/proxy_mapping.py` | Keep in Deformation as pure transform. | Medium | Proxy component compatibility. |
| `_zscore` | 259-267 | Normalizes admitted component series. | No | No | No | `DataHubBridge` | B | `src/structural_inputs/proxy_mapping.py` | Keep in Deformation as pure transform. | Medium | Numeric output changes. |

### `src/data/external_downloads.py`

Pre-Phase-A module responsibility: direct external download/cache/parse for CISS, SRISK, CoVaR.

Post-Phase-A state: this Deformation module is a deprecated fail wrapper. The
active CISS/SRISK/CoVaR acquisition implementation now lives in Harvester
`harvester.providers.external_indicators`.

| Symbol | Lines | Current responsibility | External HTTP | API keys | Raw/cache/provider data | Importers / callers | Cat | Target location | Migration action | Priority | Risk if moved |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| `ManualDownloadRequired` | 53-62 | Manual fallback error for publisher download failures. | No | No | Cache path metadata | `fetch_external_indicator`, tests | A/D | Harvester provider errors | Move to Harvester or replace with Harvester acquisition error. | High | Tests and manual fallback messages. |
| `ExternalIndicator` | 66-71 | Provider indicator descriptor with URL and instructions. | No | No | Provider metadata | Constants, fetch functions | A | Harvester provider config | Move to Harvester provider definitions. | High | Provider config location changes. |
| `_ssl_context` | 117-123 | SSL context helper. | No | No | No | `_download` | A | Harvester HTTP helper | Move with acquisition code. | Medium | TLS behavior. |
| `_download` | 126-138 | Downloads via curl then urllib. | Yes | No | Raw provider response | `fetch_external_indicator` | A | Harvester acquisition client | Move to Harvester. | Critical | Direct external fetch. |
| `_resolve_cache` | 141-144 | Resolves/creates external raw cache path. | No | No | Raw external cache | Fetch/write functions | A | Harvester raw cache policy | Move to Harvester. | Critical | Cache path compatibility. |
| `_parse_ciss_csv` | 147-155 | Parses ECB CISS CSV. | No | No | Provider parse output | `fetch_external_indicator` | A | Harvester parser | Move with CISS provider. | High | Schema parsing. |
| `_parse_srisk_csv` | 158-167 | Parses SRISK CSV. | No | No | Provider parse output | `fetch_external_indicator` | A | Harvester parser | Move with SRISK provider. | High | Schema parsing. |
| `_parse_covar_csv` | 170-182 | Parses CoVaR CSV. | No | No | Provider parse output | `fetch_external_indicator` | A | Harvester parser | Move with CoVaR provider. | High | Schema parsing. |
| `fetch_external_indicator` | 192-220 | Downloads/caches/parses one external indicator. | Yes | No | Raw external cache | `scripts/fetch_full_benchmark_panel.py`, tests | A | Harvester acquisition command/provider | First safe migration candidate; replace Deformation module with fail/deprecated wrapper after script cutover. | Critical | Benchmark panel script currently imports it. |
| `fetch_all_external` | 223-241 | Fetches all external indicators and collects manual errors. | Yes via child | No | Raw external cache | Potential script/test callers | A | Harvester acquisition command | Move to Harvester. | High | Missing indicator behavior. |
| `merge_external_into_frame` | 244-253 | Merges fetched external series into a frame. | No | No | Uses provider output | `scripts/fetch_full_benchmark_panel.py` | A/D | Harvester release builder or Workbench evidence builder | If combining provider evidence before release, move to Harvester; not Deformation. | High | Benchmark panel composition. |
| `write_template_csv` | 256-268 | Writes manual CSV schema template to cache. | No | No | Raw/manual provider cache | tests/manual workflow | A | Harvester CLI/manual ingestion helper | Move to Harvester. | Medium | Manual fallback workflow. |

Phase A result:

`src/data/external_downloads.py` was the cleanest first migration candidate because it was clearly external acquisition and weakly coupled to Deformation analysis. Phase A resolved the direct blocker by replacing `scripts/fetch_full_benchmark_panel.py` with a fail wrapper and moving the CISS/SRISK/CoVaR acquisition owner to Harvester. Deformation `src/data/external_downloads.py` now preserves old names but raises `RuntimeError` before any acquisition can occur.

### `src/benchmarks/historical_replay.py`

Module responsibility: mixed historical benchmark acquisition and Deformation benchmark transforms.

| Symbol | Lines | Current responsibility | External HTTP | API keys | Raw/cache/provider data | Importers / callers | Cat | Target location | Migration action | Priority | Risk if moved |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| `HistoricalCase` | 30-35 | Case metadata. | No | No | No | Historical replay functions/scripts | B | `src/benchmarks/historical_replay.py` or case registry | Keep in Deformation. | Low | None. |
| `fetch_fred_graph_series` | 98-106 | FRED graph CSV acquisition and local cache. | Yes via child | No | FRED raw cache | `fetch_default_fred_frame` | A | Harvester FRED provider/replay evidence release | Replace with admitted benchmark panel input. | High | Historical replay scripts. |
| `_download_fred_graph_csv` | 109-122 | Curl/urllib FRED download. | Yes | No | Raw provider response | `fetch_fred_graph_series` | A | Harvester FRED provider | Move/remove. | High | Direct acquisition. |
| `_parse_fred_graph_csv` | 125-133 | FRED CSV parser. | No | No | Provider parse output | `fetch_fred_graph_series` | A | Harvester FRED parser | Move with provider. | Medium | Historical data parsing. |
| `_ssl_context` | 136-142 | SSL helper. | No | No | No | `_download_fred_graph_csv` | A | Harvester HTTP helper | Move/remove. | Low | TLS behavior. |
| `fetch_default_fred_frame` | 145-148 | Fetches default benchmark FRED series. | Yes via child | No | FRED raw cache | `run_historical_replay` | A | Harvester replay evidence builder | Replace with admitted panel load. | High | Replay default behavior. |
| `weekly_frame` | 151-156 | Resamples frame to weekly case window. | No | No | No | `run_historical_replay` | B | Deformation benchmark transform | Keep; input should be admitted panel. | Medium | Resampling affects metrics. |
| `rolling_zscore` | 159-166 | Rolling z-score calculation. | No | No | No | `build_structural_signals` | B | Deformation benchmark transform | Keep. | Medium | Metric behavior. |
| `build_structural_signals` | 169-199 | Maps benchmark evidence to M/D/K/X-like replay indicators. | No | No | No | Replay/backtest functions | B | Deformation benchmark transform | Keep, but document as benchmark transform not acquisition. | Medium | Benchmark interpretation changes. |
| `backtest_warning_metrics` | 202-240 | Event warning metrics. | No | No | No | `run_historical_replay` | B | Deformation benchmark evaluation | Keep. | Low | Metrics compatibility. |
| `backtest_state_metrics` | 243-284 | State-action event metrics. | No | No | No | `run_historical_replay` | B | Deformation benchmark evaluation | Keep. | Low | Metrics compatibility. |
| `_event_observation_index` | 287-296 | Aligns event date to observation index. | No | No | No | Backtest metrics | B | Deformation benchmark evaluation | Keep. | Low | Event alignment. |
| `run_historical_replay` | 299-324 | Orchestrates replay; fetches default raw data if no `raw` provided. | Conditional | No | Conditional provider data | Scripts/public baseline module | B/D split | Keep transform; require admitted `raw` input | Change default from acquisition to explicit admitted evidence input. | High | Scripts expecting no-arg fetch will break. |

Acquisition vs structural-input split:

- Move: `fetch_fred_graph_series`, `_download_fred_graph_csv`, `_parse_fred_graph_csv`, `_ssl_context`, `fetch_default_fred_frame`.
- Keep: case metadata, resampling, z-scoring, signal construction, metrics.
- Cutover requirement: `run_historical_replay(raw=None)` must stop fetching; require admitted benchmark panel or load through `AdmittedEvidenceHub`.

### `src/research_corpus/providers/brevan_howard.py`

Module responsibility: external narrative corpus discovery/archive for Brevan Howard/BH Macro materials.

| Symbol | Lines | Current responsibility | External HTTP | API keys | Raw/cache/provider data | Importers / callers | Cat | Target location | Migration action | Priority | Risk if moved |
|---|---:|---|---|---|---|---|---|---|---|---|---|
| `BrevanHowardProvider` | 26-162 | Discovers and archives public research corpus documents; writes manifests. | Yes | No | Raw corpus archive + manifests | Provider package, tests | A | Harvester/corpus acquisition layer | Move to Harvester or a dedicated corpus harvester; Deformation consumes released corpus index. | Medium | Research corpus tests and paths. |
| `BrevanHowardProvider.__init__` | 44-55 | Configures local raw/manifest roots and HTTP settings. | No | No | Raw corpus path config | Class users | A | Harvester corpus provider config | Move. | Medium | Path compatibility. |
| `local_root` | 58-59 | Raw corpus output path. | No | No | Raw corpus path | Class methods | A | Harvester corpus storage policy | Move. | Low | Path changes. |
| `local_manifest_root` | 62-63 | Corpus manifest output path. | No | No | Manifest path | Class methods | A | Harvester release/provenance | Move. | Low | Path changes. |
| `seed_documents` | 65-82 | Static official corpus seeds. | No | No | Provider metadata | `discover`, `archive` | A | Harvester corpus provider | Move. | Low | None. |
| `discover` | 84-98 | Fetches index pages and extracts relevant document links. | Yes | No | Provider discovery | Tests/manual corpus workflows | A | Harvester corpus provider | Move. | Medium | Discovery results may shift. |
| `archive_seed` | 100-134 | Downloads/writes corpus document and manifest. | Yes if download | No | Raw corpus + manifest | `archive` | A | Harvester corpus release builder | Move; publish admitted corpus index. | Medium | Manifest compatibility. |
| `archive` | 136-138 | Archives multiple seeds. | Yes if download | No | Raw corpus + manifests | Provider package/tests | A | Harvester corpus CLI/provider | Move. | Medium | Workflow paths. |
| `_seed` | 140-150 | Builds normalized seed metadata. | No | No | Provider metadata | Class methods | A | Harvester corpus provider | Move. | Low | None. |
| `_local_path_for` | 152-157 | Derives local corpus path. | No | No | Raw corpus path | `archive_seed` | A | Harvester corpus storage policy | Move. | Low | Path compatibility. |
| `_fetch_bytes` | 159-162 | Performs HTTP download. | Yes | No | Raw provider bytes | `discover`, `archive_seed` | A | Harvester HTTP helper | Move. | High | Direct external fetch. |
| `classify_document` | 165-181 | Classifies corpus document type. | No | No | Corpus metadata | `discover`, tests | A/D | Harvester corpus metadata helper; compatibility import if needed | Move with corpus provider. | Low | Classification compatibility. |
| `normalize_seed` | 184-193 | Normalizes Brevan Howard seed metadata. | No | No | Corpus metadata | tests | A/D | Harvester corpus metadata helper | Move with corpus provider. | Low | Tests. |
| `_LinkParser` | 196-206 | HTML link parser. | No | No | Provider discovery parser | `_extract_links` | A | Harvester corpus provider | Move. | Low | Discovery behavior. |
| `_extract_links` | 209-212 | Extracts absolute links from HTML. | No | No | Provider discovery parser | `discover` | A | Harvester corpus provider | Move. | Low | Discovery behavior. |
| `_looks_relevant` | 215-223 | Filters relevant provider links. | No | No | Provider discovery policy | `discover` | A | Harvester corpus provider | Move. | Low | Discovery behavior. |
| `_title_from_url` | 226-229 | Builds title from URL. | No | No | Provider metadata | `discover` | A | Harvester corpus provider | Move. | Low | Title compatibility. |

Note: this module is not market-data acquisition, and it explicitly marks corpus documents as not allowed for proxy core. It is still external acquisition and should not remain owned by Deformation long-term.

## Prioritized Migration Order

1. `src/data/external_downloads.py`
   - Why first: smallest, clearly acquisition-only, no structural semantics.
   - Blocker: resolved in Phase A; `scripts/fetch_full_benchmark_panel.py` is now a fail wrapper.
   - Target: Harvester provider/acquisition command for CISS/SRISK/CoVaR plus release builder integration.

2. `src/data/adapters/public_adapters.py`
   - Why second: provider adapters are cleanly identifiable and map directly to Harvester provider files.
   - Blocker: `create_data_hub` registration and DataHub mock tests.
   - Target: `Workbench/data_providers/structural-risk-harvester/src/harvester/providers/`.

3. `src/data/data_sources.py`
   - Why third: largest and mixed.
   - Split into:
     - Harvester providers: `HTTPClient`, FRED/H41/SEC/Treasury/AlphaVantage/Polygon/Nasdaq.
     - Test fixtures: `MockDataSource`.
     - Deformation structural input transforms: proxy component parse/z-score/aggregation only.
     - Deprecated shim: `DataSourceFactory`.

4. `src/data/gateway/data_hub.py`
   - Why fourth: runtime assembly dependency and API/UI expectations make it risky.
   - Target: replace provider branch with `AdmittedEvidenceHub`; move provider registry into Harvester `ProviderHub`.

5. `src/data/gateway/bridge.py`
   - Why fifth: it is the current runtime bridge and contains useful structural aggregation logic.
   - Target: `src/structural_inputs/snapshot_builder.py` consuming `AdmittedEvidenceBundle`.

6. `src/benchmarks/historical_replay.py`
   - Why later: mixed acquisition and Deformation benchmark evaluation.
   - Target: move FRED fetching to Harvester; keep replay transforms.

7. `src/research_corpus/providers/brevan_howard.py`
   - Why later: not market proxy acquisition, but still external corpus acquisition.
   - Target: corpus Harvester or Harvester provider subpackage.

## Cutover Plan

### Phase A Decision Note

Inspection result:

- `scripts/fetch_full_benchmark_panel.py` was an acquisition script. It fetched FRED graph CSVs via `src.benchmarks.historical_replay.fetch_fred_graph_series`, fetched CISS/SRISK/CoVaR via `src.data.external_downloads`, wrote runtime caches, built derived spreads, and wrote a merged wide benchmark CSV.
- It was not imported by runtime code or tests as a Python module, but it was referenced by `scripts/run_information_tests.py` as a prerequisite for a local benchmark panel.
- The external-indicator portion has a clear Harvester home: provider/acquisition code under `Workbench/data_providers/structural-risk-harvester/src/harvester/providers/`, exposed by the Harvester CLI.

Chosen migration option:

- Move the CISS/SRISK/CoVaR acquisition owner to Harvester by adding `harvester.providers.external_indicators` and a `harvester fetch-external-indicators` CLI command.
- Replace Deformation `scripts/fetch_full_benchmark_panel.py` with an explicit deprecated fail wrapper. It does not silently proxy to Harvester.
- Replace Deformation `src/data/external_downloads.py` with a deprecated fail wrapper that preserves old names but raises `RuntimeError`.

Why:

- This removes active external acquisition from Deformation immediately.
- It avoids a hidden Framework -> Harvester acquisition call.
- It keeps the old command/import surface noisy and self-explanatory for migration users.
- Full benchmark release composition can be handled in a later Harvester release-builder pass without touching `public_adapters.py`, `data_sources.py`, or `data_hub.py`.

### Phase A: `external_downloads.py` to Harvester or fail wrapper

Actions:

1. Add Harvester-side acquisition module for CISS/SRISK/CoVaR.
2. Add Harvester CLI command or release-builder hook to publish these indicators as admitted evidence.
3. Replace `scripts/fetch_full_benchmark_panel.py` with a fail wrapper instead of importing `src.data.external_downloads`.
4. Replace Deformation `src/data/external_downloads.py` with a fail wrapper:
   - message: "External downloads moved to Structural Risk Harvester."
   - no HTTP
   - no cache writes
5. Move tests from direct download behavior to Harvester tests; keep one compatibility test that wrapper fails clearly.

Acceptance:

- `rg "src.data.external_downloads" scripts src tests` shows only compatibility tests or none.
- Boundary tests no longer need to allow `src/data/external_downloads.py` as acquisition.

### Phase B: `public_adapters.py` to Harvester providers registry

Actions:

1. Create/extend Harvester provider interface:
   - `ProviderRequest`
   - `ProviderResult`
   - `ProviderAdapter`
   - `ProviderHub`
2. Move provider adapters by family:
   - `fred.py`
   - `h41.py`
   - `treasury.py`
   - `sec.py`
   - `ecb.py`
   - `cftc.py`
   - `alpha_vantage.py`
   - `polygon.py`
   - `nasdaq_data_link.py`
   - `stooq.py`
   - `tiingo.py`
   - `cboe.py`
   - `imf.py`
3. Update Harvester release builder to own provider credentials, retry/rate-limit, and raw cache.
4. Keep Deformation `public_adapters.py` as deprecated shim until `create_data_hub` no longer imports it.

Acceptance:

- Deformation no longer constructs provider adapters.
- Provider API keys are read only in Harvester.

### Phase C: split `data_sources.py`

Actions:

1. Move concrete provider sources and `HTTPClient` to Harvester.
2. Move `MockDataSource` to tests/fixtures or a clearly named testing module.
3. Extract pure proxy mapping math to:

```text
src/structural_inputs/
├── __init__.py
├── proxy_mapping.py
├── snapshot_builder.py
└── schema.py
```

4. Delete raw in-memory provider cache behavior from Deformation transforms.
5. Keep `DataSourceFactory` only as a deprecated compatibility shim until runtime assembly is cut over.

Acceptance:

- `src/data/data_sources.py` no longer contains provider acquisition as active logic.
- Structural proxy construction accepts admitted evidence panels, not provider requests.

### Phase D: replace `data_hub.py` provider branch with `AdmittedEvidenceHub`

Actions:

1. Introduce `StructuralInputSnapshot` and builder:

```text
AdmittedEvidenceBundle -> StructuralInputSnapshot
```

2. Update runtime assembly to load:

```text
AdmittedEvidenceHub.load_latest()
-> StructuralInputSnapshot
-> pipeline
```

3. Replace `create_data_hub()` with a fail wrapper or migration-only `create_legacy_data_hub(..., allow_legacy=True)`.
4. Move provider registry to Harvester `ProviderHub`.
5. Update API/UI pages to show evidence/provenance from admitted bundle, not live provider capability registry.

Acceptance:

- Deformation runtime can run without `src.data.gateway.data_hub.create_data_hub`.
- `src/data/gateway/data_hub.py` contains no API-key/env access.
- Boundary guard allow-list can remove `src/data/gateway/data_hub.py`.

## Phase A Completed Candidate

Completed candidate: `src/data/external_downloads.py`.

Reason:

- It is clearly external acquisition.
- It has no Deformation structural transform logic.
- It does not read API keys.
- It owns raw/manual cache behavior that belongs in Harvester.
- Its import surface is small: one script and one test file.

Former blocker:

- `scripts/fetch_full_benchmark_panel.py` imported it directly. Phase A replaced that script with an explicit fail wrapper.

Implemented Phase A changes:

1. Added Harvester external-indicator acquisition support.
2. Added `harvester fetch-external-indicators`.
3. Turned `src/data/external_downloads.py` into a fail wrapper.
4. Removed `src/data/external_downloads.py` from `LEGACY_ALLOWED`.

## Do Not Move Yet

Do not move these until `AdmittedEvidenceBundle -> StructuralInputSnapshot` exists:

- `DataHubBridge`
- proxy component parsing
- z-score/aggregation logic
- historical replay transforms

Those are framework transforms once their inputs are admitted evidence. Moving them to Harvester would put framework semantics into the evidence layer.
