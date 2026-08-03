from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import requests


# Calendar-day budget before a cached series is considered stale enough to
# re-download. Wide enough that a healthy daily feed (published T+1/T+2) is
# served from cache, tight enough that a stalled feed is retried long before
# the 10-trading-day content_freshness alarm in the pipeline registry.
DEFAULT_MAX_CACHE_AGE_DAYS = 2


@dataclass(frozen=True)
class ExternalIndicator:
    name: str
    series_id: str
    description: str
    publisher_url: str
    instructions: str


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
)

SRISK = ExternalIndicator(
    name="SRISK",
    series_id="SRISK",
    description="NYU V-Lab aggregate SRISK for the US financial sector (USD billions, weekly).",
    publisher_url="https://vlab.stern.nyu.edu/api/v2.0/aggregate?market=US&measure=SRISK",
    instructions=(
        "Manual fallback: open https://vlab.stern.nyu.edu/srisk, select "
        "'United States, Aggregate', download CSV with columns ['Date', 'SRISK'], "
        "save as srisk.csv at the cache path."
    ),
)

COVAR = ExternalIndicator(
    name="COVAR",
    series_id="COVAR",
    description="NY Fed delta-CoVaR systemic risk measure for US financial sector.",
    publisher_url="https://www.newyorkfed.org/medialibrary/media/research/economists/adrian/CoVaR.csv",
    instructions=(
        "Manual fallback: NY Fed publishes CoVaR estimates with the Adrian-Brunnermeier "
        "replication package. Download a CSV with columns ['Date', 'CoVaR'] and save "
        "as covar.csv at the cache path."
    ),
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
)

CFTC_TFF_LEV_SP = ExternalIndicator(
    name="CFTC_TFF_LEV_SP",
    series_id="CFTC_TFF_LEV_SP",
    description=(
        "CFTC Traders in Financial Futures — Leveraged Funds net position in "
        "E-mini S&P 500 (weekly). Extreme positioning + stress onset = forced-delever risk."
    ),
    publisher_url=(
        "https://publicreporting.cftc.gov/resource/gpe5-46if.csv?"
        "$select=report_date_as_yyyy_mm_dd,market_and_exchange_names,"
        "lev_money_positions_long,lev_money_positions_short"
        "&$where=upper(market_and_exchange_names)%20like%20%27%25E-MINI%20S%26P%20500%25%27"
        "&$order=report_date_as_yyyy_mm_dd"
        "&$limit=50000"
    ),
    instructions=(
        "Manual fallback: open https://publicreporting.cftc.gov/Commitments-of-Traders/"
        "TFF-Futures-Only/gpe5-46if, filter E-MINI S&P 500, export CSV with report date "
        "and leveraged money long/short columns as cftc_tff_lev_sp.csv."
    ),
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
)

# Verified Markets API keyids (2026-07-12 probe). Full paper J=5 not published under
# guessed PDPOSGSC-L26/L611 names; register the live partial-maturity observations.
NYFED_PD_TREASURY_LE2Y = ExternalIndicator(
    name="NYFED_PD_TREASURY_LE2Y",
    series_id="NYFED_PD_TREASURY_LE2Y",
    description="NY Fed PD net Treasury coupons due ≤2y (PDPOSGSC-L2, weekly).",
    publisher_url="https://markets.newyorkfed.org/api/pd/get/PDPOSGSC-L2.json",
    instructions="Manual fallback: save PDPOSGSC-L2 JSON/CSV as nyfed_pd_treasury_le2y.csv with Date,value.",
)

NYFED_PD_TREASURY_GT11Y = ExternalIndicator(
    name="NYFED_PD_TREASURY_GT11Y",
    series_id="NYFED_PD_TREASURY_GT11Y",
    description="NY Fed PD net Treasury coupons due >11y (PDPOSGSC-G11, weekly).",
    publisher_url="https://markets.newyorkfed.org/api/pd/get/PDPOSGSC-G11.json",
    instructions="Manual fallback: save PDPOSGSC-G11 JSON/CSV as nyfed_pd_treasury_gt11y.csv with Date,value.",
)

FINRA_MARGIN_DEBT = ExternalIndicator(
    name="FINRA_MARGIN_DEBT",
    series_id="FINRA_MARGIN_DEBT",
    description="FINRA debit balances in customers' securities margin accounts (monthly, USD millions).",
    publisher_url="https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics",
    instructions=(
        "Manual fallback: download FINRA Margin Statistics CSV from finra.org and save "
        "as finra_margin_debt.csv with columns Date,DebitBalances. "
        "FRED series BOGZ1FL663067003Q remains the quarterly Fed Z.1 equivalent."
    ),
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


def _canonical_cache_text(indicator_name: str, series: pd.Series) -> str:
    """Write slim Date/value CSV so naive readers never see raw JSON/SDMX."""
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
    return frame.to_csv(index=False)


def _normalize_cache_file(cache_path: Path, indicator_name: str, series: pd.Series) -> None:
    """Rewrite cache to canonical CSV after a successful parse."""
    try:
        cache_path.write_text(_canonical_cache_text(indicator_name, series), encoding="utf-8")
    except OSError:
        pass


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
    return (pd.Timestamp.today().normalize() - last.normalize()).days > max_age_days


def _merge_cached_history(
    cache_path: Path, parser: Callable[[str], pd.Series], fresh: pd.Series
) -> pd.Series:
    """Extend, never shorten: publishers that serve only a rolling window must
    not truncate the history already archived on disk."""
    if fresh.empty or not cache_path.exists():
        return fresh
    try:
        cached = parser(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return fresh
    if cached.empty:
        return fresh
    kept = cached[~cached.index.isin(fresh.index)]
    return pd.concat([kept, fresh]).sort_index()


def fetch_external_indicator(
    indicator: ExternalIndicator,
    *,
    cache_dir: Path | str,
    refresh: bool = False,
    timeout_sec: int = 90,
    max_cache_age_days: int = DEFAULT_MAX_CACHE_AGE_DAYS,
) -> pd.Series:
    cache_path = _resolve_cache(cache_dir, indicator)
    parser = _PARSERS[indicator.name]

    if cache_path.exists() and not refresh:
        try:
            series = parser(cache_path.read_text(encoding="utf-8"))
            # Heal legacy JSON-as-csv / SDMX-wide caches in place.
            raw_head = cache_path.read_text(encoding="utf-8")[:200].lstrip()
            needs_normalize = raw_head.startswith("{") or (
                indicator.name == "CISS" and "KEY,FREQ" in raw_head
            )
            if needs_normalize and not series.empty:
                _normalize_cache_file(cache_path, indicator.name, series)
            # Only a cache inside its freshness budget short-circuits the
            # download; a stale one falls through and is re-fetched. The
            # handler below still falls back to it if the publisher is down.
            if not _cache_is_stale(series, max_age_days=max_cache_age_days):
                return series
        except Exception:
            pass

    try:
        text = _download(indicator.publisher_url, timeout_sec=timeout_sec)
        series = _merge_cached_history(cache_path, parser, parser(text))
        _normalize_cache_file(cache_path, indicator.name, series)
        return series
    except Exception as exc:
        if cache_path.exists():
            try:
                return parser(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
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
    for indicator in KNOWN_INDICATORS:
        try:
            out[indicator.series_id] = fetch_external_indicator(
                indicator,
                cache_dir=cache_dir,
                refresh=refresh,
            )
        except ManualDownloadRequired as exc:
            if not skip_unavailable:
                raise
            errors[indicator.name] = str(exc)
    if errors:
        out["__errors__"] = pd.Series(errors)  # type: ignore[assignment]
    return out


def external_series_to_long_panel(series_map: dict[str, pd.Series], *, vintage_date: str) -> pd.DataFrame:
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
                "source_id": "external_public",
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


def _download(url: str, *, timeout_sec: int) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "StructuralRiskHarvester/0.1.0"},
        timeout=timeout_sec,
    )
    response.raise_for_status()
    return response.text


def _parse_ofr_fsi_csv(text: str) -> pd.Series:
    frame = pd.read_csv(StringIO(text))
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


def _parse_ciss_csv(text: str) -> pd.Series:
    frame = pd.read_csv(StringIO(text))
    cols = {c.upper(): c for c in frame.columns}
    if "TIME_PERIOD" not in cols or "OBS_VALUE" not in cols:
        raise ValueError("Unexpected CISS CSV schema")
    dates = pd.to_datetime(frame[cols["TIME_PERIOD"]], errors="coerce")
    values = pd.to_numeric(frame[cols["OBS_VALUE"]], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="CISS")
    return out[~out.index.isna()].dropna().sort_index()


def _parse_srisk_csv(text: str) -> pd.Series:
    frame = pd.read_csv(StringIO(text))
    date_col = next((c for c in frame.columns if c.lower() in {"date", "time_period"}), None)
    value_col = next((c for c in frame.columns if c.lower() in {"srisk", "obs_value", "value"}), None)
    if date_col is None or value_col is None:
        raise ValueError("Unexpected SRISK CSV schema; need Date and SRISK columns")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="SRISK")
    return out[~out.index.isna()].dropna().sort_index()


def _parse_covar_csv(text: str) -> pd.Series:
    frame = pd.read_csv(StringIO(text))
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


def _parse_cftc_tff_lev_sp(text: str) -> pd.Series:
    frame = pd.read_csv(StringIO(text))
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


def _parse_nyfed_pd_treasury(text: str, *, series_name: str = "NYFED_PD_TREASURY_NET") -> pd.Series:
    text = text.strip()
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


def _parse_finra_margin_debt(text: str) -> pd.Series:
    frame = pd.read_csv(StringIO(text))
    date_col = next((c for c in frame.columns if c.lower() in {"date", "month", "year_month"}), None)
    value_col = next(
        (
            c
            for c in frame.columns
            if c.lower() in {"debitbalances", "debit_balances", "margin_debt", "value", "obs_value"}
        ),
        None,
    )
    if date_col is None or value_col is None:
        raise ValueError("Unexpected FINRA margin CSV; need Date and DebitBalances")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="FINRA_MARGIN_DEBT")
    return out[~out.index.isna()].dropna().sort_index()


_PARSERS: dict[str, Callable[[str], pd.Series]] = {
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
    "write_template_csv",
]
