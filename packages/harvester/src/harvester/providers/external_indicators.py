from __future__ import annotations

import logging
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from harvester.http_gateway import EndpointSpec, OwnedHTTPGateway

logger = logging.getLogger(__name__)

ExternalPayload = str | bytes
ExternalParser = Callable[[ExternalPayload], pd.Series]


# Calendar-day budget before a cached series is considered stale enough to
# re-download. Wide enough that a healthy daily feed (published T+1/T+2) is
# served from cache, tight enough that a stalled feed is retried long before
# the 10-trading-day content_freshness alarm in the pipeline registry.
DEFAULT_MAX_CACHE_AGE_DAYS = 2

# The ECB CISS SDMX export contains the complete historical series and is
# larger than the generic 2 MB gateway budget.  Keep a finite provider-owned
# budget rather than disabling response limits; the normalized cache is much
# smaller and remains the durable snapshot.
EXTERNAL_INDICATOR_MAX_RESPONSE_BYTES = 8_000_000


@dataclass(frozen=True)
class ExternalIndicator:
    name: str
    series_id: str
    description: str
    publisher_url: str
    instructions: str
    # The publisher/authority is part of measurement identity.  Keep the
    # legacy default only for third-party callers constructing an ad-hoc
    # indicator; all registered indicators below set it explicitly.
    authority_id: str = "external_public"
    response_format: str = "text"
    acquisition_mode: str = "automated"
    proxy_env_var: str = ""


class ManualDownloadRequired(RuntimeError):
    """Raised when a publisher URL is unreachable and a manual CSV is needed."""

    def __init__(self, indicator: str, expected_path: Path, instructions: str) -> None:
        self.indicator = indicator
        self.expected_path = expected_path
        self.instructions = instructions
        super().__init__(
            f"{indicator}: publisher download failed. Place a CSV at {expected_path}.\n{instructions}"
        )


CISS = ExternalIndicator(
    name="CISS",
    series_id="CISS",
    description="ECB Composite Indicator of Systemic Stress (euro area, daily).",
    publisher_url=(
        "https://data-api.ecb.europa.eu/service/data/CISS/D.U2.Z0Z.4F.EC.SS_CIN.IDX"
        "?format=csvdata"
    ),
    instructions=(
        "Manual fallback: download daily CISS from the ECB Data Portal, export as CSV "
        "with columns ['TIME_PERIOD', 'OBS_VALUE'], save as ciss.csv at the cache path."
    ),
    authority_id="ecb",
)

SRISK = ExternalIndicator(
    name="SRISK",
    series_id="SRISK",
    description="NYU V-Lab aggregate SRISK for the US financial sector (USD billions, monthly manual snapshot).",
    publisher_url="https://vlab.stern.nyu.edu/srisk",
    instructions=(
        "Manual monthly source: sign in at https://vlab.stern.nyu.edu/srisk, select "
        "United States / Aggregate SRISK, download the CSV with columns ['Date', 'SRISK'], "
        "and save it as srisk.csv at the cache path. The V-Lab MCP is not treated as an "
        "unauthenticated production transport."
    ),
    authority_id="nyu_vlab",
    acquisition_mode="manual",
)

COVAR = ExternalIndicator(
    name="COVAR",
    series_id="COVAR",
    description="NY Fed delta-CoVaR systemic risk measure for US financial sector.",
    publisher_url=(
        "https://www.newyorkfed.org/medialibrary/media/research/data_indicators/"
        "data_2014_sr348_CoVaR.zip"
    ),
    instructions=(
        "The official archive is a quarterly firm-level Adrian-Brunnermeier panel, not a "
        "single aggregate time series. Until an explicit aggregate selector is approved, "
        "prepare a canonical CSV with columns ['Date', 'CoVaR'] and save it as covar.csv."
    ),
    authority_id="nyfed",
    response_format="zip",
    acquisition_mode="manual",
)

OFR_FSI = ExternalIndicator(
    name="OFR_FSI",
    series_id="OFR_FSI",
    description="OFR Financial Stress Index (daily, 33 indicators, positive = above-avg stress).",
    # Direct CSV export (the chart page HTML is not parseable as FSI data).
    publisher_url=(
        "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
    ),
    instructions=(
        "Manual fallback: visit https://www.financialresearch.gov/financial-stress-index/, "
        "use the 'Download all data' button on the interactive chart to export CSV. "
        "Save with columns ['date', 'OFR_FSI'] as ofr_fsi.csv at the cache path. "
        "Updated daily with ~T+2 business day lag."
    ),
    authority_id="ofr",
)

CFTC_TFF_LEV_SP = ExternalIndicator(
    name="CFTC_TFF_LEV_SP",
    series_id="CFTC_TFF_LEV_SP",
    description=(
        "CFTC Traders in Financial Futures — Leveraged Funds net position in "
        "E-mini S&P 500 (weekly). Extreme positioning + stress onset = forced-delever risk."
    ),
    publisher_url=(
        "https://publicreporting.cftc.gov/resource/gpe5-46if.json?"
        "$select=report_date_as_yyyy_mm_dd,market_and_exchange_names,"
        "lev_money_positions_long,lev_money_positions_short"
        "&$where=upper(market_and_exchange_names)%20like%20%27E-MINI%20S%26P%20500%25%27"
        "%20and%20upper(market_and_exchange_names)%20not%20like%20%27MICRO%20E-MINI%25%27"
        "&$order=report_date_as_yyyy_mm_dd"
        "&$limit=50000"
    ),
    instructions=(
        "Manual fallback: open https://publicreporting.cftc.gov/Commitments-of-Traders/"
        "TFF-Futures-Only/gpe5-46if, filter E-MINI S&P 500, export CSV with report date "
        "and leveraged money long/short columns as cftc_tff_lev_sp.csv."
    ),
    authority_id="cftc",
    proxy_env_var="HARVESTER_CFTC_PROXY_URL",
)

NYFED_PD_TREASURY_NET = ExternalIndicator(
    name="NYFED_PD_TREASURY_NET",
    series_id="NYFED_PD_TREASURY_NET",
    description=(
        "NY Fed Primary Dealer net outright Treasury positions excluding TIPS "
        "(PDPOSGST-TOT, weekly). Direct shadow-leverage / dealer balance-sheet observation."
    ),
    publisher_url="https://markets.newyorkfed.org/api/pd/get/PDPOSGST-TOT.json",
    instructions=(
        "Manual fallback: download "
        "https://markets.newyorkfed.org/api/pd/get/PDPOSGST-TOT.json "
        "or export Primary Dealer Statistics PDPOSGST-TOT; save as "
        "nyfed_pd_treasury_net.csv with columns Date,value."
    ),
    authority_id="nyfed",
)

# Verified Markets API keyids (2026-07-12 probe). Full paper J=5 not published under
# guessed PDPOSGSC-L26/L611 names; register the live partial-maturity observations.
NYFED_PD_TREASURY_LE2Y = ExternalIndicator(
    name="NYFED_PD_TREASURY_LE2Y",
    series_id="NYFED_PD_TREASURY_LE2Y",
    description="NY Fed PD net Treasury coupons due ≤2y (PDPOSGSC-L2, weekly).",
    publisher_url="https://markets.newyorkfed.org/api/pd/get/PDPOSGSC-L2.json",
    instructions="Manual fallback: save PDPOSGSC-L2 JSON/CSV as nyfed_pd_treasury_le2y.csv with Date,value.",
    authority_id="nyfed",
)

NYFED_PD_TREASURY_GT11Y = ExternalIndicator(
    name="NYFED_PD_TREASURY_GT11Y",
    series_id="NYFED_PD_TREASURY_GT11Y",
    description="NY Fed PD net Treasury coupons due >11y (PDPOSGSC-G11, weekly).",
    publisher_url="https://markets.newyorkfed.org/api/pd/get/PDPOSGSC-G11.json",
    instructions="Manual fallback: save PDPOSGSC-G11 JSON/CSV as nyfed_pd_treasury_gt11y.csv with Date,value.",
    authority_id="nyfed",
)

FINRA_MARGIN_DEBT = ExternalIndicator(
    name="FINRA_MARGIN_DEBT",
    series_id="FINRA_MARGIN_DEBT",
    description="FINRA debit balances in customers' securities margin accounts (monthly, USD millions).",
    publisher_url="https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx",
    instructions=(
        "Manual fallback: download FINRA Margin Statistics CSV from finra.org and save "
        "as finra_margin_debt.csv with columns Date,DebitBalances. "
        "FRED series BOGZ1FL663067003Q remains the quarterly Fed Z.1 equivalent."
    ),
    authority_id="finra",
    response_format="xlsx",
)

KNOWN_INDICATORS: tuple[ExternalIndicator, ...] = (
    CISS,
    SRISK,
    COVAR,
    OFR_FSI,
    CFTC_TFF_LEV_SP,
    NYFED_PD_TREASURY_NET,
    NYFED_PD_TREASURY_LE2Y,
    NYFED_PD_TREASURY_GT11Y,
    FINRA_MARGIN_DEBT,
)

EXTERNAL_ENDPOINTS: dict[tuple[str, str], EndpointSpec] = {
    (indicator.authority_id, indicator.name): EndpointSpec(
        provider=indicator.authority_id,
        endpoint_id=indicator.name,
        url=indicator.publisher_url,
        allowed_hosts=frozenset({urlparse(indicator.publisher_url).hostname or ""}),
        proxy_env_var=indicator.proxy_env_var,
    )
    for indicator in KNOWN_INDICATORS
}


def _canonical_cache_text(indicator_name: str, series: pd.Series) -> str:
    """Write slim CSV for parsed indicators without a raw-schema contract."""
    frame = pd.DataFrame(
        {
            "Date" if indicator_name != "CISS" else "TIME_PERIOD": pd.to_datetime(series.index),
            "value" if indicator_name != "CISS" else "OBS_VALUE": pd.to_numeric(series, errors="coerce"),
        }
    ).dropna()
    if indicator_name == "CISS":
        frame.columns = ["TIME_PERIOD", "OBS_VALUE"]
        frame["TIME_PERIOD"] = pd.to_datetime(frame["TIME_PERIOD"]).dt.strftime("%Y-%m-%d")
    elif indicator_name == "OFR_FSI":
        # Keep the registry / freshness_validator date_column ("date") and the
        # historical ofr_fsi.csv schema so content clocks do not KeyError.
        frame.columns = ["date", "OFR_FSI"]
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    else:
        frame.columns = ["Date", "value"]
        frame["Date"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
    return str(frame.to_csv(index=False))


def _normalize_cache_file(cache_path: Path, indicator_name: str, series: pd.Series) -> None:
    """Rewrite cache to canonical CSV after a successful parse."""
    try:
        _atomic_write_text(cache_path, _canonical_cache_text(indicator_name, series))
    except OSError:
        logger.warning("Failed to normalize indicator cache: %s", cache_path, exc_info=True)


def _atomic_write_text(path: Path, text: str) -> None:
    """Replace a cache only after the complete response has been written."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to remove temporary indicator cache: %s", temporary_path, exc_info=True)


def _payload_text(payload: ExternalPayload) -> str:
    if isinstance(payload, bytes):
        return payload.decode("utf-8-sig", errors="replace")
    return payload


def _read_cache_payload(cache_path: Path, indicator: ExternalIndicator) -> ExternalPayload:
    """Read binary source caches before they are normalized to canonical CSV."""
    raw = cache_path.read_bytes()
    if indicator.response_format in {"xlsx", "zip"} and raw[:2] == b"PK":
        return raw
    return raw.decode("utf-8-sig", errors="replace")


def _cache_is_stale(series: pd.Series, *, max_age_days: int) -> bool:
    """True when the newest cached observation is older than the budget.

    Without this the cache branch below returns unconditionally, so a cache
    written once is served forever and the feed silently freezes.
    """
    if series.empty:
        return True
    last = pd.Timestamp(series.index.max())
    if pd.isna(last):
        return True
    return bool((pd.Timestamp.today().normalize() - last.normalize()).days > max_age_days)


def _merge_cached_history(
    cache_path: Path, indicator: ExternalIndicator, parser: ExternalParser, fresh: pd.Series
) -> pd.Series:
    """Extend, never shorten: publishers that serve only a rolling window must
    not truncate the history already archived on disk."""
    if fresh.empty or not cache_path.exists():
        return fresh
    try:
        cached = parser(_read_cache_payload(cache_path, indicator))
    except Exception:
        logger.warning("Failed to parse cached indicator history: %s", cache_path, exc_info=True)
        return fresh
    if cached.empty:
        return fresh
    kept = cached[~cached.index.isin(fresh.index)]
    return pd.concat([kept, fresh]).sort_index()


def read_cached_external_indicator(
    indicator: ExternalIndicator,
    *,
    cache_dir: Path | str,
) -> pd.Series | None:
    """Read a registered manual cache without treating it as a transport failure."""
    cache_path = _resolve_cache(cache_dir, indicator)
    if not cache_path.exists():
        return None
    try:
        return _PARSERS[indicator.name](_read_cache_payload(cache_path, indicator))
    except Exception:
        logger.warning("Cached external indicator is invalid: %s", cache_path, exc_info=True)
        return None


def fetch_external_indicator(
    indicator: ExternalIndicator,
    *,
    cache_dir: Path | str,
    refresh: bool = False,
    timeout_sec: int = 90,
    max_cache_age_days: int = DEFAULT_MAX_CACHE_AGE_DAYS,
    gateway: OwnedHTTPGateway | None = None,
) -> pd.Series:
    cache_path = _resolve_cache(cache_dir, indicator)
    parser = _PARSERS[indicator.name]

    if indicator.acquisition_mode == "manual":
        cached = read_cached_external_indicator(indicator, cache_dir=cache_dir)
        if cached is not None:
            return cached
        raise ManualDownloadRequired(
            indicator=indicator.name,
            expected_path=cache_path,
            instructions=indicator.instructions,
        )

    if cache_path.exists() and not refresh:
        try:
            cached_payload = _read_cache_payload(cache_path, indicator)
            series = parser(cached_payload)
            # Heal legacy JSON-as-csv / SDMX-wide caches in place.
            raw_head = _payload_text(cached_payload)[:200].lstrip()
            needs_normalize = raw_head.startswith("{") or (
                indicator.name == "CISS" and "KEY,FREQ" in raw_head
            ) or indicator.response_format in {"xlsx", "zip"} and raw_head.startswith("PK")
            if needs_normalize and not series.empty:
                _normalize_cache_file(cache_path, indicator.name, series)
            # Only a cache inside its freshness budget short-circuits the
            # download; a stale one falls through and is re-fetched. The
            # handler below still falls back to it if the publisher is down.
            if not _cache_is_stale(series, max_age_days=max_cache_age_days):
                return series
        except Exception:
            logger.warning("Failed to parse cached indicator: %s", cache_path, exc_info=True)

    try:
        owns_gateway = gateway is None
        client = gateway or OwnedHTTPGateway(
            endpoint_registry=EXTERNAL_ENDPOINTS,
            headers={"User-Agent": "StructuralRiskHarvester/0.1.0"},
            timeout_sec=timeout_sec,
            max_response_bytes=EXTERNAL_INDICATOR_MAX_RESPONSE_BYTES,
        )
        try:
            text = _download(indicator, gateway=client)
        finally:
            if owns_gateway:
                client.close()
        if indicator.name == "CFTC_TFF_LEV_SP":
            # Validate the publisher response before any replacement.  Store a
            # readable CSV snapshot even though the Socrata transport is JSON;
            # the cache remains self-parseable and preserves the long schema.
            series = parser(text)
            cache_text = _cftc_frame(text).to_csv(index=False)
            try:
                _atomic_write_text(cache_path, cache_text)
            except OSError:
                logger.warning("Failed to persist raw CFTC indicator cache: %s", cache_path, exc_info=True)
            return series
        series = _merge_cached_history(cache_path, indicator, parser, parser(text))
        _normalize_cache_file(cache_path, indicator.name, series)
        return series
    except Exception as exc:
        if cache_path.exists():
            try:
                return parser(_read_cache_payload(cache_path, indicator))
            except Exception:
                logger.warning("Cached indicator fallback is also invalid: %s", cache_path, exc_info=True)
        raise ManualDownloadRequired(
            indicator=indicator.name,
            expected_path=cache_path,
            instructions=f"{indicator.instructions}\nUnderlying error: {exc}",
        ) from exc


def fetch_all_external(
    *,
    cache_dir: Path | str,
    refresh: bool = False,
    skip_unavailable: bool = True,
) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}
    with OwnedHTTPGateway(
        endpoint_registry=EXTERNAL_ENDPOINTS,
        headers={"User-Agent": "StructuralRiskHarvester/0.1.0"},
        max_response_bytes=EXTERNAL_INDICATOR_MAX_RESPONSE_BYTES,
    ) as gateway:
        for indicator in KNOWN_INDICATORS:
            if indicator.acquisition_mode == "manual":
                cached = read_cached_external_indicator(indicator, cache_dir=cache_dir)
                if cached is not None:
                    out[indicator.series_id] = cached
                continue
            try:
                out[indicator.series_id] = fetch_external_indicator(
                    indicator,
                    cache_dir=cache_dir,
                    refresh=refresh,
                    gateway=gateway,
                )
            except ManualDownloadRequired as exc:
                if not skip_unavailable:
                    raise
                errors[indicator.name] = str(exc)
    if errors:
        out["__errors__"] = pd.Series(errors)  # type: ignore[assignment]
    return out


def external_series_to_long_panel(
    series_map: dict[str, pd.Series],
    *,
    vintage_date: str,
    indicators: Mapping[str, ExternalIndicator] | None = None,
) -> pd.DataFrame:
    """Convert external observations without collapsing publisher identity.

    ``indicators`` is optional for compatibility with callers that pass only
    series. Registered indicators are resolved by series id; unknown ad-hoc
    series retain the explicit legacy ``external_public`` identity instead of
    guessing a publisher.
    """
    known = {indicator.series_id: indicator for indicator in KNOWN_INDICATORS}
    if indicators:
        known.update({str(key): value for key, value in indicators.items()})
    frames: list[pd.DataFrame] = []
    for series_id, series in series_map.items():
        if series_id == "__errors__":
            continue
        cleaned = pd.to_numeric(series, errors="coerce").dropna()
        if cleaned.empty:
            continue
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(cleaned.index),
                "series_id": series_id,
                "source_id": str(known.get(series_id).authority_id if series_id in known else "external_public"),
                "source_series_id": series_id,
                "value": cleaned.to_numpy(dtype=float),
                "unit": "",
                "frequency": "irregular",
                "vintage_date": vintage_date,
                "quality_flag": 0,
            }
        )
        frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=[
                "date",
                "series_id",
                "source_id",
                "source_series_id",
                "value",
                "unit",
                "frequency",
                "vintage_date",
                "quality_flag",
            ]
        )
    return pd.concat(frames, ignore_index=True).sort_values(["series_id", "date"]).reset_index(drop=True)


def write_template_csv(indicator_name: str, *, cache_dir: Path | str) -> Path:
    indicator = next((item for item in KNOWN_INDICATORS if item.name == indicator_name), None)
    if indicator is None:
        raise ValueError(f"Unknown indicator {indicator_name}")
    cache_path = _resolve_cache(cache_dir, indicator)
    if cache_path.exists():
        return cache_path
    if indicator.name == "CISS":
        cache_path.write_text("TIME_PERIOD,OBS_VALUE\n2024-01-01,0.10\n", encoding="utf-8")
    elif indicator.name == "OFR_FSI":
        cache_path.write_text("date,OFR_FSI\n2024-01-01,0.0\n", encoding="utf-8")
    else:
        cache_path.write_text(f"Date,{indicator.name}\n2024-01-01,0.0\n", encoding="utf-8")
    return cache_path


def _download(
    indicator: ExternalIndicator,
    *,
    gateway: OwnedHTTPGateway,
) -> ExternalPayload:
    response = gateway.fetch(
        indicator.authority_id,
        indicator.name,
    )
    response.raise_for_status()
    return response.content if indicator.response_format in {"xlsx", "zip"} else str(response.text)


def _parse_ofr_fsi_csv(payload: ExternalPayload) -> pd.Series:
    frame = pd.read_csv(StringIO(_payload_text(payload)))
    date_col = next((c for c in frame.columns if c.lower() in {"date", "time_period"}), None)
    # Accept both "OFR_FSI" (underscore, canonical cache) and "OFR FSI" (space,
    # the raw header from financialresearch.gov's CSV export) so a fresh
    # re-download does not silently fail to parse.
    value_col = next(
        (c for c in frame.columns if c.lower().replace(" ", "_") in {"ofr_fsi", "fsi"}
         or c.lower() in {"obs_value", "value"}),
        None,
    )
    if date_col is None or value_col is None:
        raise ValueError("Unexpected OFR_FSI CSV schema; need Date and OFR_FSI columns")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="OFR_FSI")
    return out[~out.index.isna()].dropna().sort_index()


def _resolve_cache(cache_dir: Path | str, indicator: ExternalIndicator) -> Path:
    base = Path(cache_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{indicator.name.lower()}.csv"


def _parse_ciss_csv(payload: ExternalPayload) -> pd.Series:
    text = _payload_text(payload)
    # The ECB endpoint is documented with ``format=csvdata`` but has returned
    # both CSV and SDMX Generic XML over time (and through different gateway
    # paths).  Parse both representations so a content-negotiation change does
    # not silently turn a fresh release into a stale-cache fallback.
    if text.lstrip().startswith("<"):
        return _parse_ciss_sdmx_xml(text)
    frame = pd.read_csv(StringIO(text))
    cols = {c.upper(): c for c in frame.columns}
    if "TIME_PERIOD" not in cols or "OBS_VALUE" not in cols:
        raise ValueError("Unexpected CISS CSV schema")
    dates = pd.to_datetime(frame[cols["TIME_PERIOD"]], errors="coerce")
    values = pd.to_numeric(frame[cols["OBS_VALUE"]], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="CISS")
    return out[~out.index.isna()].dropna().sort_index()


def _xml_local_name(tag: str) -> str:
    """Return an XML tag/attribute local name, ignoring its namespace."""
    return tag.rsplit("}", 1)[-1]


def _xml_attribute(element: ET.Element, name: str) -> str | None:
    """Read an XML attribute by local name (Generic XML may namespace it)."""
    for key, value in element.attrib.items():
        if key == name or _xml_local_name(key) == name:
            return value
    return None


def _parse_ciss_sdmx_xml(text: str) -> pd.Series:
    """Parse ECB SDMX GenericData observations into the canonical CISS series.

    The response is bounded by ``OwnedHTTPGateway`` before reaching this
    parser.  Rejecting DTD/entity declarations here additionally prevents an
    untrusted provider response from enabling XML entity expansion if this
    parser is called directly in a fixture or maintenance script.
    """
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("CISS SDMX XML must not contain DTD or entity declarations")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("Unexpected CISS SDMX XML document") from exc

    rows: list[tuple[str, str]] = []
    for observation in root.iter():
        if _xml_local_name(observation.tag) != "Obs":
            continue
        dimension: ET.Element | None = None
        value_element: ET.Element | None = None
        for child in observation.iter():
            if child is observation:
                continue
            local = _xml_local_name(child.tag)
            if local == "ObsDimension":
                candidate_id = _xml_attribute(child, "id")
                if dimension is None or candidate_id == "TIME_PERIOD":
                    dimension = child
            elif local == "ObsValue" and value_element is None:
                value_element = child
        if dimension is None or value_element is None:
            continue
        date_value = _xml_attribute(dimension, "value")
        observation_value = _xml_attribute(value_element, "value")
        if date_value and observation_value:
            rows.append((date_value, observation_value))

    if not rows:
        raise ValueError("Unexpected CISS SDMX XML schema; no observations found")
    frame = pd.DataFrame(rows, columns=["TIME_PERIOD", "OBS_VALUE"])
    dates = pd.to_datetime(frame["TIME_PERIOD"], errors="coerce")
    values = pd.to_numeric(frame["OBS_VALUE"], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="CISS")
    out = out[~out.index.isna()].dropna()
    # Generic SDMX can repeat a date when a publisher adds dimensions.  The
    # endpoint is a single CISS series, so retain the last observation rather
    # than emitting duplicate index values downstream.
    return out.groupby(level=0).last().sort_index()


def _parse_srisk_csv(payload: ExternalPayload) -> pd.Series:
    frame = pd.read_csv(StringIO(_payload_text(payload)))
    date_col = next((c for c in frame.columns if c.lower() in {"date", "time_period"}), None)
    value_col = next((c for c in frame.columns if c.lower() in {"srisk", "obs_value", "value"}), None)
    if date_col is None or value_col is None:
        raise ValueError("Unexpected SRISK CSV schema; need Date and SRISK columns")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="SRISK")
    return out[~out.index.isna()].dropna().sort_index()


def _parse_covar_csv(payload: ExternalPayload) -> pd.Series:
    if isinstance(payload, bytes) and payload[:2] == b"PK":
        raise ValueError(
            "NY Fed CoVaR archive is a quarterly firm-level panel; "
            "an explicit aggregate selector is required before scalar parsing"
        )
    frame = pd.read_csv(StringIO(_payload_text(payload)))
    date_col = next((c for c in frame.columns if c.lower() in {"date", "time_period"}), None)
    value_col = next(
        (c for c in frame.columns if c.lower() in {"covar", "delta_covar", "deltacovar", "obs_value", "value"}),
        None,
    )
    if date_col is None or value_col is None:
        raise ValueError("Unexpected CoVaR CSV schema; need Date and CoVaR columns")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="COVAR")
    return out[~out.index.isna()].dropna().sort_index()


def _cftc_frame(payload: ExternalPayload) -> pd.DataFrame:
    text = _payload_text(payload).strip()
    if text.startswith("[") or text.startswith("{"):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("CFTC Socrata response is not valid JSON") from exc
        if isinstance(decoded, dict):
            decoded = decoded.get("data", decoded.get("results", decoded))
        if not isinstance(decoded, list):
            raise ValueError("CFTC Socrata JSON response must contain a row array")
        frame = pd.DataFrame(decoded)
    else:
        frame = pd.read_csv(StringIO(text))
    market_col = next((c for c in frame.columns if c.lower() == "market_and_exchange_names"), None)
    if market_col is not None:
        frame = frame[~frame[market_col].astype(str).str.upper().str.startswith("MICRO E-MINI")]
    return frame


def _parse_cftc_tff_lev_sp(payload: ExternalPayload) -> pd.Series:
    frame = _cftc_frame(payload)
    market_col = next((c for c in frame.columns if c.lower() == "market_and_exchange_names"), None)
    if market_col is not None:
        # The Socrata wildcard for the standard contract also matches the
        # micro E-mini. Keep the target series semantically exact even when a
        # hand-exported response contains both instruments.
        frame = frame[~frame[market_col].astype(str).str.upper().str.startswith("MICRO E-MINI")]
    date_col = next(
        (c for c in frame.columns if "report_date" in c.lower() or c.lower() == "date"),
        None,
    )
    long_col = next((c for c in frame.columns if "lev_money" in c.lower() and "long" in c.lower()), None)
    short_col = next((c for c in frame.columns if "lev_money" in c.lower() and "short" in c.lower()), None)
    if date_col is None or long_col is None or short_col is None:
        raise ValueError("Unexpected CFTC TFF schema; need report date + lev money long/short")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    net = pd.to_numeric(frame[long_col], errors="coerce") - pd.to_numeric(frame[short_col], errors="coerce")
    out = pd.Series(net.to_numpy(), index=dates, name="CFTC_TFF_LEV_SP")
    # Aggregate duplicate markets/dates by sum (rare) then weekly last.
    out = out[~out.index.isna()].dropna().groupby(level=0).sum().sort_index()
    return out


def _parse_nyfed_pd_treasury(payload: ExternalPayload, *, series_name: str = "NYFED_PD_TREASURY_NET") -> pd.Series:
    text = _payload_text(payload).strip()
    if text.startswith("{"):
        import json

        payload = json.loads(text)
        rows = payload.get("pd", {}).get("timeseries", [])
        if not rows:
            raise ValueError("NY Fed PD JSON missing timeseries rows")
        dates = pd.to_datetime([row.get("asofdate") for row in rows], errors="coerce")
        values = pd.to_numeric([row.get("value") for row in rows], errors="coerce")
        out = pd.Series(np.asarray(values, dtype=float), index=dates, name=series_name)
        return out[~out.index.isna()].dropna().sort_index()
    frame = pd.read_csv(StringIO(text))
    date_col = next((c for c in frame.columns if c.lower() in {"date", "asofdate", "as_of_date"}), None)
    value_col = next((c for c in frame.columns if c.lower() in {"value", "obs_value"}), None)
    if date_col is None or value_col is None:
        raise ValueError("Unexpected NY Fed PD CSV schema")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name=series_name)
    return out[~out.index.isna()].dropna().sort_index()


def _parse_nyfed_pd_treasury_le2y(text: str) -> pd.Series:
    return _parse_nyfed_pd_treasury(text, series_name="NYFED_PD_TREASURY_LE2Y")


def _parse_nyfed_pd_treasury_gt11y(text: str) -> pd.Series:
    return _parse_nyfed_pd_treasury(text, series_name="NYFED_PD_TREASURY_GT11Y")


def _parse_finra_margin_debt(payload: ExternalPayload) -> pd.Series:
    if isinstance(payload, bytes) and payload[:2] == b"PK":
        frame = pd.read_excel(BytesIO(payload), sheet_name=0)
    else:
        frame = pd.read_csv(StringIO(_payload_text(payload)))
    normalized = {str(column).strip().lower().replace(" ", "").replace("_", ""): column for column in frame.columns}
    date_col = next(
        (normalized[key] for key in ("date", "month", "yearmonth", "year-month") if key in normalized),
        None,
    )
    value_col = next((normalized[key] for key in ("debitbalances", "margindebt", "value", "obsvalue") if key in normalized), None)
    if value_col is None:
        value_col = next(
            (column for key, column in normalized.items() if "debitbalances" in key),
            None,
        )
    if date_col is None or value_col is None:
        raise ValueError("Unexpected FINRA margin CSV; need Date and DebitBalances")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="FINRA_MARGIN_DEBT")
    return out[~out.index.isna()].dropna().sort_index()


_PARSERS: dict[str, ExternalParser] = {
    "CISS": _parse_ciss_csv,
    "SRISK": _parse_srisk_csv,
    "COVAR": _parse_covar_csv,
    "OFR_FSI": _parse_ofr_fsi_csv,
    "CFTC_TFF_LEV_SP": _parse_cftc_tff_lev_sp,
    "NYFED_PD_TREASURY_NET": _parse_nyfed_pd_treasury,
    "NYFED_PD_TREASURY_LE2Y": _parse_nyfed_pd_treasury_le2y,
    "NYFED_PD_TREASURY_GT11Y": _parse_nyfed_pd_treasury_gt11y,
    "FINRA_MARGIN_DEBT": _parse_finra_margin_debt,
}


__all__ = [
    "CISS",
    "COVAR",
    "CFTC_TFF_LEV_SP",
    "FINRA_MARGIN_DEBT",
    "KNOWN_INDICATORS",
    "ManualDownloadRequired",
    "NYFED_PD_TREASURY_GT11Y",
    "NYFED_PD_TREASURY_LE2Y",
    "NYFED_PD_TREASURY_NET",
    "OFR_FSI",
    "SRISK",
    "ExternalIndicator",
    "external_series_to_long_panel",
    "fetch_all_external",
    "fetch_external_indicator",
    "read_cached_external_indicator",
    "write_template_csv",
]
