"""
LEGACY ACQUISITION SHIM.
This module contains legacy public-provider acquisition logic retained for
backward compatibility.
New Deformation code must not import this module for provider acquisition.
New external data acquisition belongs in Structural Risk Harvester.
Deformation's official data boundary is src/data_access/, which consumes
Harvester-published admitted evidence releases.
retire_after: 2026-10-15
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

from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Iterable, Mapping

import pandas as pd

from src.data.contracts import (
    EventRecord,
    EventRequest,
    FilingRecord,
    FilingRequest,
    PositionRecord,
    PositionRequest,
    SeriesRequest,
    SeriesResult,
)
from src._legacy.data.data_sources import (
    AlphaVantageDataSource,
    FREDDataSource,
    FederalReserveH41DataSource,
    HTTPClient,
    MockDataSource,
    NasdaqDataLinkDataSource,
    PolygonDataSource,
    SECEDGARDataSource,
    TreasuryFiscalDataSource,
)
from src.data.paths import resolve_fred_cache_dir


def _require_http(client: HTTPClient | None) -> HTTPClient:
    if client is None:
        raise RuntimeError("legacy HTTP adapter is not configured")
    return client


def _series_result(provider: str, request: SeriesRequest, frame: pd.DataFrame, metadata: Mapping[str, Any] | None = None) -> SeriesResult:
    ordered = frame.sort_index()
    combined_metadata = {
        "preset_name": request.preset_name,
        "channel": request.channel,
        "measurement_block": request.measurement_block,
        "evidence_role": request.evidence_role,
        "jurisdiction_or_scope": request.jurisdiction_or_scope,
    }
    if metadata:
        combined_metadata.update(dict(metadata))
    return SeriesResult(
        provider=provider,
        request_key=request.request_key(),
        frame=ordered,
        metadata=combined_metadata,
    )


def _coerce_date(value: Any) -> str | None:
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return None
    return str(stamp.strftime("%Y-%m-%d"))


def _best_value(row: Mapping[str, Any], candidates: tuple[str, ...], default: Any = None) -> Any:
    for key in candidates:
        if key in row and row[key] not in {None, ""}:
            return row[key]
    return default


@dataclass
class MockSeriesAdapter:
    provider: str
    seed: int = 42

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        source = MockDataSource(seed=self.seed)
        frame = source.fetch([request.request_key()], start=start, end=end)
        return _series_result(self.provider, request, frame, metadata={"mode": "mock"})


@dataclass
class MockEventAdapter:
    provider: str

    def fetch_events(self, request: EventRequest, start: str, end: str) -> list[EventRecord]:
        return [
            EventRecord(
                provider=self.provider,
                event_date=end,
                event_type=request.event_type or "MOCK_EVENT",
                title=f"{self.provider.upper()} mock event",
                summary="Synthetic event emitted by the mock DataHub adapter.",
                metadata=dict(request.metadata),
            )
        ]


@dataclass
class MockFilingAdapter:
    provider: str = "sec"

    def fetch_filings(self, request: FilingRequest, start: str, end: str) -> list[FilingRecord]:
        return [
            FilingRecord(
                provider=self.provider,
                cik=str(request.cik or "0000000000").zfill(10),
                filing_date=end,
                form=request.form_types[0] if request.form_types else "10-K",
                accession_number="0000000000-26-000001",
                filing_url="https://www.sec.gov/",
                metadata={"mode": "mock", **dict(request.metadata)},
            )
        ]


@dataclass
class MockPositionAdapter:
    provider: str = "cftc"

    def fetch_positions(self, request: PositionRequest, start: str, end: str) -> list[PositionRecord]:
        return [
            PositionRecord(
                provider=self.provider,
                report_date=end,
                market_name=request.market_name or "Mock Market",
                market_code=request.market_code,
                category=request.category or "leveraged_funds",
                long=100.0,
                short=90.0,
                spreading=5.0,
                open_interest=1000.0,
                metadata={"mode": "mock", **dict(request.metadata)},
            )
        ]


@dataclass
class FREDSeriesAdapter:
    api_key: str | None = None
    fallback_seed: int = 42
    http: HTTPClient | None = None
    cache_dir: str | None = None
    max_workers: int = 6
    provider: str = "fred"

    def __post_init__(self) -> None:
        self.source = FREDDataSource(
            api_key=self.api_key,
            fallback_seed=self.fallback_seed,
            http=self.http,
            cache_dir=self.cache_dir or str(resolve_fred_cache_dir()),
            max_workers=self.max_workers,
        )

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        if not request.series_id:
            raise ValueError("FRED series requests require `series_id`.")
        frame = self.source.fetch([request.request_key()], start=start, end=end)
        return _series_result(self.provider, request, frame, metadata={"endpoint_family": "fred"})


@dataclass
class FedH41SeriesAdapter:
    csv_url: str
    date_column: str = "date"
    fallback_seed: int = 42
    http: HTTPClient | None = None
    provider: str = "fed_h41"

    def __post_init__(self) -> None:
        self.source = FederalReserveH41DataSource(
            csv_url=self.csv_url,
            date_column=self.date_column,
            fallback_seed=self.fallback_seed,
            http=self.http,
        )

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        if not request.field:
            raise ValueError("Fed H.4.1 requests require `field`.")
        frame = self.source.fetch([request.request_key()], start=start, end=end)
        return _series_result(self.provider, request, frame, metadata={"release": "H.4.1"})


@dataclass
class TreasurySeriesAdapter:
    fallback_seed: int = 42
    http: HTTPClient | None = None
    base_url: str = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
    provider: str = "treasury"

    def __post_init__(self) -> None:
        self.source = TreasuryFiscalDataSource(
            fallback_seed=self.fallback_seed,
            http=self.http,
            base_url=self.base_url,
        )

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        if not request.dataset or not request.field:
            raise ValueError("Treasury series requests require `dataset` and `field`.")
        frame = self.source.fetch([request.request_key()], start=start, end=end)
        return _series_result(
            self.provider,
            request,
            frame,
            metadata={"dataset": request.dataset, "field": request.field},
        )


@dataclass
class TreasuryEventAdapter:
    http: HTTPClient | None = None
    base_url: str = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
    provider: str = "treasury"

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient()

    def fetch_events(self, request: EventRequest, start: str, end: str) -> list[EventRecord]:
        resource = request.resource or request.dataset
        if not resource:
            raise ValueError("Treasury event requests require `resource` or `dataset`.")
        date_field = str(request.metadata.get("date_field", "record_date"))
        title_fields = request.metadata.get("title_fields", ["security_type", "transaction_type", "account_type"])
        if isinstance(title_fields, str):
            title_fields = [title_fields]
        url = (
            f"{self.base_url.rstrip('/')}/{resource.lstrip('/')}"
            f"?filter={date_field}:gte:{start},{date_field}:lte:{end}"
            f"&format=json&page[size]=1000"
        )
        payload = _require_http(self.http).get_json(url)
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        records: list[EventRecord] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            event_date = _coerce_date(row.get(date_field))
            if event_date is None:
                continue
            title_parts = [str(row.get(field, "")).strip() for field in title_fields if str(row.get(field, "")).strip()]
            title = " / ".join(title_parts) or f"Treasury event {event_date}"
            records.append(
                EventRecord(
                    provider=self.provider,
                    event_date=event_date,
                    event_type=request.event_type or str(request.metadata.get("default_event_type", "TREASURY_EVENT")),
                    title=title,
                    summary=str(row.get(request.metadata.get("summary_field", ""), "")).strip() or None,
                    metadata={"resource": resource, "raw": dict(row)},
                )
            )
        return records


@dataclass
class SECSeriesAdapter:
    user_agent: str
    fallback_seed: int = 42
    http: HTTPClient | None = None
    provider: str = "sec"

    def __post_init__(self) -> None:
        self.source = SECEDGARDataSource(
            user_agent=self.user_agent,
            fallback_seed=self.fallback_seed,
            http=self.http,
        )

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        if not request.cik:
            raise ValueError("SEC series requests require `cik`.")
        frame = self.source.fetch([request.request_key()], start=start, end=end)
        return _series_result(self.provider, request, frame, metadata={"measure": "daily_filing_count"})


@dataclass
class SECFilingAdapter:
    user_agent: str
    http: HTTPClient | None = None
    base_url: str = "https://data.sec.gov/submissions"
    provider: str = "sec"

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient(default_headers={"User-Agent": self.user_agent})

    def fetch_filings(self, request: FilingRequest, start: str, end: str) -> list[FilingRecord]:
        if not request.cik:
            raise ValueError("SEC filing requests require `cik`.")
        cik = str(request.cik).zfill(10)
        payload = _require_http(self.http).get_json(f"{self.base_url.rstrip('/')}/CIK{cik}.json")
        recent = payload.get("filings", {}).get("recent", {}) if isinstance(payload, dict) else {}
        if not isinstance(recent, Mapping):
            return []
        forms_filter = {form.upper() for form in request.form_types}
        dates = list(recent.get("filingDate", []))
        forms = list(recent.get("form", []))
        accessions = list(recent.get("accessionNumber", []))
        primary_documents = list(recent.get("primaryDocument", []))
        descriptions = list(recent.get("primaryDocDescription", []))

        records: list[FilingRecord] = []
        for idx, filed_at in enumerate(dates):
            filing_date = _coerce_date(filed_at)
            form = str(forms[idx]) if idx < len(forms) else ""
            if filing_date is None or filing_date < start or filing_date > end:
                continue
            if forms_filter and form.upper() not in forms_filter:
                continue
            accession_number = str(accessions[idx]) if idx < len(accessions) else None
            primary_document = str(primary_documents[idx]) if idx < len(primary_documents) else None
            accession_path = (accession_number or "").replace("-", "")
            filing_url = None
            if accession_path and primary_document:
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary_document}"
            records.append(
                FilingRecord(
                    provider=self.provider,
                    cik=cik,
                    filing_date=filing_date,
                    form=form,
                    accession_number=accession_number,
                    primary_document=primary_document,
                    filing_url=filing_url,
                    facts_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json" if request.include_facts else None,
                    metadata={
                        "description": str(descriptions[idx]) if idx < len(descriptions) else "",
                    },
                )
            )
        return records


@dataclass
class ECBSeriesAdapter:
    http: HTTPClient | None = None
    base_url: str = "https://data-api.ecb.europa.eu/service/data"
    provider: str = "ecb"

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient()

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        flow_ref = request.dataset or str(request.metadata.get("flow_ref", "EXR"))
        key = request.series_id or request.key
        if not key:
            raise ValueError("ECB series requests require `series_id` or `key`.")
        url = (
            f"{self.base_url.rstrip('/')}/{flow_ref}/{key}"
            f"?startPeriod={start}&endPeriod={end}&format=csvdata"
        )
        csv_text = _require_http(self.http).get_text(url)
        frame = pd.read_csv(StringIO(csv_text))
        if frame.empty:
            raise ValueError("ECB response was empty.")
        date_column = next(
            (candidate for candidate in ("TIME_PERIOD", "TIME_PERIOD:obsTime", "DATE", "date") if candidate in frame.columns),
            None,
        )
        value_column = next(
            (candidate for candidate in ("OBS_VALUE", "value", "OBS_VALUE:Value") if candidate in frame.columns),
            None,
        )
        if date_column is None or value_column is None:
            raise ValueError("ECB response did not contain expected date/value columns.")
        dates = pd.to_datetime(frame[date_column], errors="coerce")
        values = pd.to_numeric(frame[value_column], errors="coerce")
        series = pd.Series(values.to_numpy(), index=dates, name=request.request_key()).dropna()
        out = pd.DataFrame({request.request_key(): series}).sort_index()
        return _series_result(self.provider, request, out, metadata={"flow_ref": flow_ref, "key": key})


@dataclass
class CFTCPositionAdapter:
    http: HTTPClient | None = None
    base_url: str = "https://publicreporting.cftc.gov/resource"
    provider: str = "cftc"
    field_candidates: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "date": ("report_date_as_yyyy_mm_dd", "as_of_date_in_form_yyyy_mm_dd", "report_date"),
            "market_name": ("market_and_exchange_names", "contract_market_name"),
            "market_code": ("cftc_contract_market_code", "market_code"),
            "long": ("noncomm_positions_long_all", "noncommercial_positions_long_all", "leveraged_funds_long_all", "long_positions"),
            "short": ("noncomm_positions_short_all", "noncommercial_positions_short_all", "leveraged_funds_short_all", "short_positions"),
            "spreading": ("noncomm_positions_spreading_all", "noncommercial_positions_spreading_all", "spreading_positions"),
            "open_interest": ("open_interest_all", "open_interest"),
        }
    )

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient()

    def fetch_positions(self, request: PositionRequest, start: str, end: str) -> list[PositionRecord]:
        resource = request.resource or request.dataset_id or str(request.metadata.get("resource", ""))
        if not resource:
            raise ValueError("CFTC position requests require `resource` or `dataset_id`.")
        date_field = self.field_candidates["date"][0]
        url = (
            f"{self.base_url.rstrip('/')}/{resource}.json"
            f"?$limit=50000&$order={date_field}%20asc"
        )
        rows = _require_http(self.http).get_json(url)
        if not isinstance(rows, list):
            return []

        items: list[PositionRecord] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            report_date = _coerce_date(_best_value(row, self.field_candidates["date"]))
            if report_date is None or report_date < start or report_date > end:
                continue
            market_name = str(_best_value(row, self.field_candidates["market_name"], "")).strip()
            market_code = _best_value(row, self.field_candidates["market_code"])
            if request.market_name and request.market_name.lower() not in market_name.lower():
                continue
            if request.market_code and str(request.market_code) != str(market_code):
                continue
            items.append(
                PositionRecord(
                    provider=self.provider,
                    report_date=report_date,
                    market_name=market_name or "Unknown Market",
                    market_code=str(market_code) if market_code is not None else None,
                    category=request.category,
                    long=_to_float(_best_value(row, self.field_candidates["long"])),
                    short=_to_float(_best_value(row, self.field_candidates["short"])),
                    spreading=_to_float(_best_value(row, self.field_candidates["spreading"])),
                    open_interest=_to_float(_best_value(row, self.field_candidates["open_interest"])),
                    metadata={"resource": resource, "raw": dict(row)},
                )
            )
        return items


@dataclass
class AlphaVantageSeriesAdapter:
    api_key: str | None = None
    fallback_seed: int = 42
    http: HTTPClient | None = None
    provider: str = "alpha_vantage"

    def __post_init__(self) -> None:
        self.source = AlphaVantageDataSource(api_key=self.api_key, fallback_seed=self.fallback_seed, http=self.http)

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        if not request.series_id:
            raise ValueError("Alpha Vantage requests require `series_id`, e.g. SPY:close.")
        key = request.series_id if request.series_id.upper().startswith("AV:") else f"AV:{request.series_id}"
        frame = self.source.fetch([key], start=start, end=end)
        if key in frame.columns and request.request_key() != key:
            frame = frame.rename(columns={key: request.request_key()})
        return _series_result(self.provider, request, frame, metadata={"endpoint_family": "alpha_vantage_daily_adjusted"})


@dataclass
class PolygonSeriesAdapter:
    api_key: str | None = None
    fallback_seed: int = 42
    http: HTTPClient | None = None
    provider: str = "polygon"

    def __post_init__(self) -> None:
        self.source = PolygonDataSource(api_key=self.api_key, fallback_seed=self.fallback_seed, http=self.http)

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        if not request.series_id:
            raise ValueError("Polygon requests require `series_id`, e.g. SPY:close.")
        key = request.series_id if request.series_id.upper().startswith("POLY:") else f"POLY:{request.series_id}"
        frame = self.source.fetch([key], start=start, end=end)
        if key in frame.columns and request.request_key() != key:
            frame = frame.rename(columns={key: request.request_key()})
        return _series_result(self.provider, request, frame, metadata={"endpoint_family": "polygon_aggs_daily"})


@dataclass
class NasdaqDataLinkSeriesAdapter:
    api_key: str | None = None
    fallback_seed: int = 42
    http: HTTPClient | None = None
    provider: str = "nasdaq_data_link"

    def __post_init__(self) -> None:
        self.source = NasdaqDataLinkDataSource(api_key=self.api_key, fallback_seed=self.fallback_seed, http=self.http)

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        dataset = request.series_id or request.dataset or request.key
        if not dataset:
            raise ValueError("Nasdaq Data Link requests require `series_id`, `dataset`, or `key`.")
        key = dataset if str(dataset).upper().startswith("NDL:") else f"NDL:{dataset}"
        frame = self.source.fetch([key], start=start, end=end)
        if key in frame.columns and request.request_key() != key:
            frame = frame.rename(columns={key: request.request_key()})
        return _series_result(self.provider, request, frame, metadata={"endpoint_family": "nasdaq_data_link_dataset"})


@dataclass
class StooqSeriesAdapter:
    http: HTTPClient | None = None
    base_url: str = "https://stooq.com/q/d/l/"
    provider: str = "stooq"

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient()

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        symbol = request.series_id or request.key
        if not symbol:
            raise ValueError("Stooq requests require `series_id` or `key`.")
        field = str(request.field or request.metadata.get("field", "Close"))
        d1 = start.replace("-", "")
        d2 = end.replace("-", "")
        url = f"{self.base_url}?s={symbol.lower()}&d1={d1}&d2={d2}&i=d"
        frame = _csv_date_value_frame(_require_http(self.http).get_text(url), request.request_key(), field_candidates=(field, field.title(), field.lower()))
        return _series_result(self.provider, request, frame, metadata={"symbol": symbol, "field": field, "frequency": "daily"})


@dataclass
class TiingoSeriesAdapter:
    api_key: str | None = None
    http: HTTPClient | None = None
    base_url: str = "https://api.tiingo.com/tiingo/daily"
    provider: str = "tiingo"

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient()

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        ticker = request.series_id or request.key
        if not ticker:
            raise ValueError("Tiingo requests require `series_id` or `key`.")
        token = self.api_key or str(request.metadata.get("api_key", ""))
        field = str(request.field or request.metadata.get("field", "adjClose"))
        url = f"{self.base_url.rstrip('/')}/{ticker}/prices?startDate={start}&endDate={end}"
        if token:
            url = f"{url}&token={token}"
        rows = _require_http(self.http).get_json(url, headers={"Content-Type": "application/json"})
        if not isinstance(rows, list):
            raise ValueError("Tiingo response did not contain a row list.")
        frame = _json_rows_date_value_frame(rows, request.request_key(), date_candidates=("date",), value_candidates=(field, "adjClose", "close"))
        return _series_result(self.provider, request, frame, metadata={"ticker": ticker, "field": field, "frequency": "daily"})


@dataclass
class CBOESeriesAdapter:
    http: HTTPClient | None = None
    provider: str = "cboe"
    vix_history_url: str = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient()

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        dataset = (request.series_id or request.dataset or "vix").lower()
        url = str(request.resource or request.metadata.get("url") or "")
        if not url:
            if dataset in {"vix", "vix_history", "vixcls"}:
                url = self.vix_history_url
            else:
                raise ValueError("CBOE requests require `resource`/metadata.url unless dataset is VIX.")
        field = str(request.field or request.metadata.get("field", "CLOSE"))
        frame = _csv_date_value_frame(
            _require_http(self.http).get_text(url),
            request.request_key(),
            date_candidates=("DATE", "Date", "date"),
            field_candidates=(field, field.upper(), field.title(), "CLOSE", "Close"),
        )
        frame = frame[(frame.index >= pd.to_datetime(start)) & (frame.index <= pd.to_datetime(end))]
        return _series_result(self.provider, request, frame, metadata={"dataset": dataset, "field": field, "source_url": url})


@dataclass
class GenericCSVSeriesAdapter:
    provider: str
    http: HTTPClient | None = None
    base_url: str = ""
    default_date_columns: tuple[str, ...] = ("TIME_PERIOD", "date", "Date", "DATE", "ref_area", "period")
    default_value_columns: tuple[str, ...] = ("OBS_VALUE", "value", "Value", "obs_value")

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient()

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        url = _request_url(request, self.base_url)
        if not url:
            raise ValueError(f"{self.provider} requests require `resource`, metadata.url, or dataset/key with a configured base URL.")
        date_candidates = _metadata_tuple(request.metadata, "date_columns", self.default_date_columns)
        value_candidates = _metadata_tuple(
            request.metadata,
            "value_columns",
            (request.field, *self.default_value_columns) if request.field else self.default_value_columns,
        )
        frame = _csv_date_value_frame(_require_http(self.http).get_text(url), request.request_key(), date_candidates=date_candidates, field_candidates=value_candidates)
        frame = frame[(frame.index >= pd.to_datetime(start)) & (frame.index <= pd.to_datetime(end))]
        return _series_result(self.provider, request, frame, metadata={"source_url": url, "endpoint_family": "generic_csv"})


@dataclass
class IMFSeriesAdapter:
    http: HTTPClient | None = None
    base_url: str = "https://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData"
    provider: str = "imf"

    def __post_init__(self) -> None:
        self.http = self.http or HTTPClient()

    def fetch_series(self, request: SeriesRequest, start: str, end: str) -> SeriesResult:
        url = _request_url(request, self.base_url)
        if not url:
            raise ValueError("IMF requests require `resource`, metadata.url, or dataset/key.")
        if "startPeriod=" not in url:
            joiner = "&" if "?" in url else "?"
            url = f"{url}{joiner}startPeriod={start}&endPeriod={end}"
        payload = _require_http(self.http).get_json(url)
        observations = _extract_imf_observations(payload)
        frame = pd.DataFrame({request.request_key(): observations}).sort_index()
        return _series_result(self.provider, request, frame, metadata={"source_url": url, "endpoint_family": "imf_sdmx_json"})


def _csv_date_value_frame(
    csv_text: str,
    column_name: str,
    date_candidates: tuple[str | None, ...] = ("Date", "date", "DATE", "TIME_PERIOD"),
    field_candidates: tuple[str | None, ...] = ("Close", "close", "CLOSE", "OBS_VALUE", "value"),
) -> pd.DataFrame:
    frame = pd.read_csv(StringIO(csv_text))
    if frame.empty:
        raise ValueError("CSV response was empty.")
    date_column = next((col for col in date_candidates if col and col in frame.columns), None)
    value_column = next((col for col in field_candidates if col and col in frame.columns), None)
    if date_column is None or value_column is None:
        raise ValueError("CSV response did not contain expected date/value columns.")
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    values = pd.to_numeric(frame[value_column], errors="coerce")
    series = pd.Series(values.to_numpy(), index=dates, name=column_name).dropna()
    return pd.DataFrame({column_name: series}).sort_index()


def _json_rows_date_value_frame(
    rows: list[Any],
    column_name: str,
    date_candidates: tuple[str, ...],
    value_candidates: tuple[str | None, ...],
) -> pd.DataFrame:
    dates = []
    values = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw_date = _best_value(row, date_candidates)
        raw_value = _best_value(row, tuple(item for item in value_candidates if item))
        dates.append(pd.to_datetime(raw_date, errors="coerce"))
        values.append(pd.to_numeric(raw_value, errors="coerce"))
    series = pd.Series(values, index=dates, name=column_name).dropna()
    return pd.DataFrame({column_name: series}).sort_index()


def _request_url(request: SeriesRequest, base_url: str) -> str:
    direct = request.resource or request.metadata.get("url")
    if direct:
        return str(direct)
    if request.dataset and (request.key or request.series_id):
        return f"{base_url.rstrip('/')}/{str(request.dataset).strip('/')}/{str(request.key or request.series_id).strip('/')}"
    if request.series_id and base_url:
        return f"{base_url.rstrip('/')}/{str(request.series_id).strip('/')}"
    return ""


def _metadata_tuple(metadata: Mapping[str, Any], key: str, default: tuple[str | None, ...]) -> tuple[str | None, ...]:
    value = metadata.get(key)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(str(item) for item in value)
    return default


def _extract_imf_observations(payload: Any) -> pd.Series:
    compact = payload.get("CompactData", {}) if isinstance(payload, Mapping) else {}
    dataset = compact.get("DataSet", {}) if isinstance(compact, Mapping) else {}
    series = dataset.get("Series", {}) if isinstance(dataset, Mapping) else {}
    if isinstance(series, list):
        series = series[0] if series else {}
    obs = series.get("Obs", []) if isinstance(series, Mapping) else []
    if isinstance(obs, Mapping):
        obs = [obs]
    dates = []
    values = []
    for item in obs if isinstance(obs, list) else []:
        if not isinstance(item, Mapping):
            continue
        dates.append(pd.to_datetime(item.get("@TIME_PERIOD"), errors="coerce"))
        values.append(pd.to_numeric(item.get("@OBS_VALUE"), errors="coerce"))
    return pd.Series(values, index=dates).dropna()


def _to_float(value: Any) -> float | None:
    numeric = pd.to_numeric([value], errors="coerce")[0]
    return None if pd.isna(numeric) else float(numeric)
