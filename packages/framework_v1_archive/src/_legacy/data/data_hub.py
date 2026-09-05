"""
LEGACY ACQUISITION SHIM.
retire_after: 2026-10-15
This module contains legacy public-provider acquisition logic retained for
backward compatibility.
New Deformation code must not import this module for provider acquisition.
New external data acquisition belongs in Structural Risk Harvester.
Deformation's official data boundary is src/data_access/, which consumes
Harvester-published admitted evidence releases.
Allowed temporary use:
- legacy replay
- old dashboard rendering
- compatibility tests
- migration support
Forbidden new use:
- new provider clients
- new API-key access
- new HTTP acquisition
- new raw provider cache logic
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, cast

from src.data.adapters import (
    AlphaVantageSeriesAdapter,
    CBOESeriesAdapter,
    CFTCPositionAdapter,
    ECBSeriesAdapter,
    FREDSeriesAdapter,
    FedH41SeriesAdapter,
    GenericCSVSeriesAdapter,
    IMFSeriesAdapter,
    MockEventAdapter,
    MockFilingAdapter,
    MockPositionAdapter,
    MockSeriesAdapter,
    NasdaqDataLinkSeriesAdapter,
    PolygonSeriesAdapter,
    SECFilingAdapter,
    SECSeriesAdapter,
    StooqSeriesAdapter,
    TiingoSeriesAdapter,
    TreasuryEventAdapter,
    TreasurySeriesAdapter,
)
from src.data.contracts import (
    DataRequestError,
    EventRequest,
    FetchResult,
    FilingRequest,
    PositionRequest,
    SeriesRequest,
    StructuralFetchPlan,
    StructuralPreset,
    StructuralPresetResult,
    build_structural_fetch_plan,
    default_structural_presets,
    enrich_series_request_from_preset,
)
from src._legacy.data.data_sources import HTTPClient
from src.data.gateway.source_registry import SourceRegistry
from src.data.gateway.evidence_router import EvidenceRequest, EvidenceRouter
from src.data.paths import resolve_fred_cache_dir


@dataclass
class DataHub:
    """
    Unified public-data gateway for the Data layer.

    This centralizes provider routing, auth/header conventions, retries, and
    normalized output contracts. Core should consume the normalized outputs of
    this gateway or the downstream protocol objects built from them, not raw
    provider payloads.
    """

    registry: SourceRegistry
    structural_presets: tuple[StructuralPreset, ...] = ()

    def __post_init__(self) -> None:
        self._presets_by_name = {preset.name: preset for preset in self.structural_presets}
        request_map: dict[str, list[str]] = {}
        for preset in self.structural_presets:
            for request in preset.requests:
                request_map.setdefault(request.request_key(), []).append(preset.name)
        self._request_to_presets = {key: tuple(values) for key, values in request_map.items()}

    def fetch_series(self, series_requests: Sequence[SeriesRequest | Mapping[str, Any]], start: str, end: str) -> FetchResult:
        items = []
        errors: list[DataRequestError] = []
        for raw_request in series_requests:
            try:
                request = self._coerce_series_request(raw_request)
            except Exception as exc:
                probe = SeriesRequest.from_input(raw_request)
                errors.append(DataRequestError("series", probe.provider, {"request_key": probe.request_key()}, str(exc)))
                continue
            adapter = self.registry.resolve_series(request.provider)
            if adapter is None:
                errors.append(_missing_provider("series", request.provider, {"request_key": request.request_key()}))
                continue
            try:
                items.append(adapter.fetch_series(request, start=start, end=end))
            except Exception as exc:
                errors.append(DataRequestError("series", request.provider, {"request_key": request.request_key()}, str(exc)))
        return FetchResult(
            kind="series",
            items=items,
            errors=errors,
            metadata={
                "start": start,
                "end": end,
                "preset_names": sorted({item.metadata.get("preset_name") for item in items if item.metadata.get("preset_name")}),
                "channels_touched": sorted({item.metadata.get("channel") for item in items if item.metadata.get("channel")}),
                "blocks_touched": sorted({item.metadata.get("measurement_block") for item in items if item.metadata.get("measurement_block")}),
                "evidence_roles": sorted({item.metadata.get("evidence_role") for item in items if item.metadata.get("evidence_role")}),
            },
        )

    def fetch_events(self, event_requests: Sequence[EventRequest | Mapping[str, Any]], start: str, end: str) -> FetchResult:
        items = []
        errors: list[DataRequestError] = []
        for raw_request in event_requests:
            request = EventRequest.from_input(raw_request)
            if not request.has_structural_semantics():
                errors.append(
                    DataRequestError(
                        "events",
                        request.provider,
                        {"resource": request.resource, "dataset": request.dataset},
                        "event requests must declare channel, measurement_block, and evidence_role.",
                    )
                )
                continue
            adapter = self.registry.resolve_events(request.provider)
            if adapter is None:
                errors.append(_missing_provider("events", request.provider, {"dataset": request.dataset, "resource": request.resource}))
                continue
            try:
                items.extend(adapter.fetch_events(request, start=start, end=end))
            except Exception as exc:
                errors.append(
                    DataRequestError(
                        "events",
                        request.provider,
                        {"dataset": request.dataset, "resource": request.resource},
                        str(exc),
                    )
                )
        return FetchResult(kind="events", items=items, errors=errors, metadata={"start": start, "end": end})

    def fetch_filings(self, filing_requests: Sequence[FilingRequest | Mapping[str, Any]], start: str, end: str) -> FetchResult:
        items = []
        errors: list[DataRequestError] = []
        for raw_request in filing_requests:
            request = FilingRequest.from_input(raw_request)
            if not request.has_structural_semantics():
                errors.append(
                    DataRequestError(
                        "filings",
                        request.provider,
                        {"cik": request.cik},
                        "filing requests must declare channel, measurement_block, and evidence_role.",
                    )
                )
                continue
            adapter = self.registry.resolve_filings(request.provider)
            if adapter is None:
                errors.append(_missing_provider("filings", request.provider, {"cik": request.cik}))
                continue
            try:
                items.extend(adapter.fetch_filings(request, start=start, end=end))
            except Exception as exc:
                errors.append(DataRequestError("filings", request.provider, {"cik": request.cik}, str(exc)))
        return FetchResult(kind="filings", items=items, errors=errors, metadata={"start": start, "end": end})

    def fetch_positions(self, position_requests: Sequence[PositionRequest | Mapping[str, Any]], start: str, end: str) -> FetchResult:
        items = []
        errors: list[DataRequestError] = []
        for raw_request in position_requests:
            request = PositionRequest.from_input(raw_request)
            if not request.has_structural_semantics():
                errors.append(
                    DataRequestError(
                        "positions",
                        request.provider,
                        {"resource": request.resource, "dataset_id": request.dataset_id},
                        "position requests must declare channel, measurement_block, and evidence_role.",
                    )
                )
                continue
            adapter = self.registry.resolve_positions(request.provider)
            if adapter is None:
                errors.append(_missing_provider("positions", request.provider, {"resource": request.resource, "dataset_id": request.dataset_id}))
                continue
            try:
                items.extend(adapter.fetch_positions(request, start=start, end=end))
            except Exception as exc:
                errors.append(
                    DataRequestError(
                        "positions",
                        request.provider,
                        {"resource": request.resource, "dataset_id": request.dataset_id},
                        str(exc),
                    )
                )
        return FetchResult(kind="positions", items=items, errors=errors, metadata={"start": start, "end": end})

    def fetch_market_structure(self, requests: Sequence[Mapping[str, Any]], start: str, end: str) -> FetchResult:
        errors = [
            DataRequestError(
                "market_structure",
                str(item.get("provider", "")),
                dict(item),
                "market-structure adapters are intentionally deferred for a later phase (FINRA/OCC).",
            )
            for item in requests
        ]
        return FetchResult(kind="market_structure", items=[], errors=errors, metadata={"start": start, "end": end, "status": "deferred"})

    def available_providers(self) -> dict[str, list[str]]:
        return cast(dict[str, list[str]], self.registry.available())

    def available_structural_presets(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], [preset.to_dict() for preset in self.structural_presets])

    def build_structural_plan(self, series_ids: Sequence[str]) -> StructuralFetchPlan:
        return build_structural_fetch_plan(series_ids=series_ids, presets=self.structural_presets)

    def route_evidence(self, request: EvidenceRequest | Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], EvidenceRouter(presets=self.structural_presets).route(request).to_dict())

    def provider_capabilities(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], EvidenceRouter(presets=self.structural_presets).capability_catalog())

    def fetch_structural_presets(self, preset_names: Sequence[str], start: str, end: str) -> FetchResult:
        items: list[StructuralPresetResult] = []
        errors: list[DataRequestError] = []
        for name in preset_names:
            preset = self._presets_by_name.get(str(name))
            if preset is None:
                errors.append(
                    DataRequestError(
                        "structural_presets",
                        "structural",
                        {"preset_name": str(name)},
                        "structural preset is not registered",
                    )
                )
                continue
            result = self.fetch_series(list(preset.requests), start=start, end=end)
            if result.errors:
                errors.extend(result.errors)
            preset_items = [item for item in result.items if getattr(item, "metadata", {}).get("preset_name") == preset.name]
            items.append(StructuralPresetResult(preset=preset, items=preset_items))
        return FetchResult(
            kind="structural_presets",
            items=items,
            errors=errors,
            metadata={
                "start": start,
                "end": end,
                "preset_names": list(preset_names),
            },
        )

    def _coerce_series_request(self, raw_request: SeriesRequest | Mapping[str, Any]) -> SeriesRequest:
        request = SeriesRequest.from_input(raw_request)
        if request.preset_name:
            preset = self._presets_by_name.get(str(request.preset_name))
            if preset is None:
                raise ValueError(f"unknown structural preset '{request.preset_name}'")
            return enrich_series_request_from_preset(request, preset)
        if request.has_structural_semantics():
            return request
        preset_names = self._request_to_presets.get(request.request_key(), ())
        if len(preset_names) == 1:
            preset = self._presets_by_name[preset_names[0]]
            return enrich_series_request_from_preset(request, preset)
        if len(preset_names) > 1:
            joined = ", ".join(sorted(preset_names))
            raise ValueError(
                "series request is structurally ambiguous; declare preset_name or explicit "
                f"channel/measurement_block/evidence_role. candidates: {joined}"
            )
        raise ValueError(
            "series request is not structurally admitted; declare preset_name or explicit "
            "channel/measurement_block/evidence_role."
        )


def create_data_hub(config: Mapping[str, Any], use_mock: bool = False) -> DataHub:
    registry = SourceRegistry()
    seed = int(config.get("mock_seed", 42))
    structural_presets = tuple(default_structural_presets())
    if use_mock:
        _register_mock_adapters(registry, seed=seed)
        return DataHub(registry=registry, structural_presets=structural_presets)

    ds_cfg = config.get("data_sources", {})
    if not isinstance(ds_cfg, Mapping):
        ds_cfg = {}
    api_keys = ds_cfg.get("api_keys", {})
    if not isinstance(api_keys, Mapping):
        api_keys = {}

    project_name = str(config.get("project_name", "Structural Deformation Research System")).strip()
    sec_user_agent = str(ds_cfg.get("sec_user_agent", api_keys.get("sec_user_agent") or os.getenv("SEC_USER_AGENT", ""))).strip()
    default_headers = {"User-Agent": sec_user_agent or f"{project_name} datahub/0.1"}
    http = HTTPClient(
        timeout_sec=int(ds_cfg.get("timeout_sec", 20)),
        retries=int(ds_cfg.get("retries", 2)),
        backoff_sec=float(ds_cfg.get("retry_backoff_sec", 0.5)),
        default_headers=default_headers,
    )

    registry.register_series(
        "fred",
        FREDSeriesAdapter(
            api_key=str(api_keys.get("fred") or os.getenv("FRED_API_KEY", "")).strip() or None,
            fallback_seed=seed,
            http=http,
            cache_dir=str(resolve_fred_cache_dir(dict(config))),
            max_workers=int(ds_cfg.get("fred_max_workers", 6)),
        ),
    )
    registry.register_series(
        "fed_h41",
        FedH41SeriesAdapter(
            csv_url=str(ds_cfg.get("h41_csv_url", "")),
            date_column=str(ds_cfg.get("h41_date_column", "date")),
            fallback_seed=seed,
            http=http,
        ),
        aliases=("fed", "h41"),
    )
    registry.register_series(
        "treasury",
        TreasurySeriesAdapter(
            fallback_seed=seed,
            http=http,
            base_url=str(ds_cfg.get("treasury_base_url", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service")),
        ),
        aliases=("treasury_fiscal", "fiscaldata"),
    )
    registry.register_events(
        "treasury",
        TreasuryEventAdapter(
            http=http,
            base_url=str(ds_cfg.get("treasury_base_url", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service")),
        ),
        aliases=("treasury_fiscal", "fiscaldata"),
    )
    registry.register_series(
        "sec",
        SECSeriesAdapter(
            user_agent=sec_user_agent,
            fallback_seed=seed,
            http=http,
        ),
    )
    registry.register_filings(
        "sec",
        SECFilingAdapter(
            user_agent=sec_user_agent,
            http=http,
        ),
    )
    registry.register_series(
        "ecb",
        ECBSeriesAdapter(
            http=http,
            base_url=str(ds_cfg.get("ecb_base_url", "https://data-api.ecb.europa.eu/service/data")),
        ),
    )
    registry.register_positions(
        "cftc",
        CFTCPositionAdapter(
            http=http,
            base_url=str(ds_cfg.get("cftc_base_url", "https://publicreporting.cftc.gov/resource")),
        ),
    )
    registry.register_series(
        "alpha_vantage",
        AlphaVantageSeriesAdapter(
            api_key=str(api_keys.get("alpha_vantage") or os.getenv("ALPHA_VANTAGE_API_KEY", "")).strip() or None,
            fallback_seed=seed,
            http=http,
        ),
        aliases=("av",),
    )
    registry.register_series(
        "stooq",
        StooqSeriesAdapter(
            http=http,
            base_url=str(ds_cfg.get("stooq_base_url", "https://stooq.com/q/d/l/")),
        ),
    )
    registry.register_series(
        "tiingo",
        TiingoSeriesAdapter(
            api_key=str(api_keys.get("tiingo") or os.getenv("TIINGO_API_KEY", "")).strip() or None,
            http=http,
            base_url=str(ds_cfg.get("tiingo_base_url", "https://api.tiingo.com/tiingo/daily")),
        ),
    )
    registry.register_series(
        "polygon",
        PolygonSeriesAdapter(
            api_key=str(api_keys.get("polygon") or os.getenv("POLYGON_API_KEY", "")).strip() or None,
            fallback_seed=seed,
            http=http,
        ),
        aliases=("poly",),
    )
    registry.register_series(
        "nasdaq_data_link",
        NasdaqDataLinkSeriesAdapter(
            api_key=str(api_keys.get("nasdaq_data_link") or os.getenv("NASDAQ_DATA_LINK_API_KEY", "")).strip() or None,
            fallback_seed=seed,
            http=http,
        ),
        aliases=("quandl", "ndl"),
    )
    registry.register_series("cboe", CBOESeriesAdapter(http=http))
    registry.register_series(
        "oecd",
        GenericCSVSeriesAdapter(
            provider="oecd",
            http=http,
            base_url=str(ds_cfg.get("oecd_base_url", "https://sdmx.oecd.org/public/rest/v1/data")),
        ),
    )
    registry.register_series(
        "bis",
        GenericCSVSeriesAdapter(
            provider="bis",
            http=http,
            base_url=str(ds_cfg.get("bis_base_url", "https://stats.bis.org/api/v1/data")),
        ),
    )
    registry.register_series(
        "imf",
        IMFSeriesAdapter(
            http=http,
            base_url=str(ds_cfg.get("imf_base_url", "https://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData")),
        ),
    )
    registry.register_series(
        "ffiec",
        GenericCSVSeriesAdapter(
            provider="ffiec",
            http=http,
            base_url=str(ds_cfg.get("ffiec_base_url", "")),
            default_date_columns=("date", "Date", "RCON9999", "report_date", "ReportingPeriodEndDate"),
            default_value_columns=("value", "Value", "amount", "Amount", "RCON2170", "OBS_VALUE"),
        ),
    )
    return DataHub(registry=registry, structural_presets=structural_presets)


def _register_mock_adapters(registry: SourceRegistry, seed: int) -> None:
    registry.register_series("fred", MockSeriesAdapter("fred", seed=seed))
    registry.register_series("fed_h41", MockSeriesAdapter("fed_h41", seed=seed + 1), aliases=("fed", "h41"))
    registry.register_series("treasury", MockSeriesAdapter("treasury", seed=seed + 2), aliases=("treasury_fiscal", "fiscaldata"))
    registry.register_events("treasury", MockEventAdapter("treasury"), aliases=("treasury_fiscal", "fiscaldata"))
    registry.register_series("sec", MockSeriesAdapter("sec", seed=seed + 3))
    registry.register_filings("sec", MockFilingAdapter("sec"))
    registry.register_series("ecb", MockSeriesAdapter("ecb", seed=seed + 4))
    registry.register_positions("cftc", MockPositionAdapter("cftc"))
    registry.register_series("alpha_vantage", MockSeriesAdapter("alpha_vantage", seed=seed + 5), aliases=("av",))
    registry.register_series("stooq", MockSeriesAdapter("stooq", seed=seed + 6))
    registry.register_series("tiingo", MockSeriesAdapter("tiingo", seed=seed + 7))
    registry.register_series("polygon", MockSeriesAdapter("polygon", seed=seed + 8), aliases=("poly",))
    registry.register_series("nasdaq_data_link", MockSeriesAdapter("nasdaq_data_link", seed=seed + 9), aliases=("quandl", "ndl"))
    registry.register_series("cboe", MockSeriesAdapter("cboe", seed=seed + 10))
    registry.register_series("oecd", MockSeriesAdapter("oecd", seed=seed + 11))
    registry.register_series("bis", MockSeriesAdapter("bis", seed=seed + 12))
    registry.register_series("imf", MockSeriesAdapter("imf", seed=seed + 13))
    registry.register_series("ffiec", MockSeriesAdapter("ffiec", seed=seed + 14))


def _missing_provider(kind: str, provider: str, request: dict[str, Any]) -> DataRequestError:
    return DataRequestError(kind=kind, provider=provider, request=request, message="provider is not registered in DataHub")
