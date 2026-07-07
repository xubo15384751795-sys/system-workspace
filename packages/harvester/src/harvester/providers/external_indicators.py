from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Callable

import pandas as pd
import requests


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
    publisher_url=(
        "https://www.financialresearch.gov/financial-stress-index/"
    ),
    instructions=(
        "Manual fallback: visit https://www.financialresearch.gov/financial-stress-index/, "
        "use the 'Download all data' button on the interactive chart to export CSV. "
        "Save with columns ['date', 'OFR_FSI'] as ofr_fsi.csv at the cache path. "
        "Updated daily with ~T+2 business day lag."
    ),
)

KNOWN_INDICATORS: tuple[ExternalIndicator, ...] = (CISS, SRISK, COVAR, OFR_FSI)


def fetch_external_indicator(
    indicator: ExternalIndicator,
    *,
    cache_dir: Path | str,
    refresh: bool = False,
    timeout_sec: int = 90,
) -> pd.Series:
    cache_path = _resolve_cache(cache_dir, indicator)
    parser = _PARSERS[indicator.name]

    if cache_path.exists() and not refresh:
        try:
            return parser(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    try:
        text = _download(indicator.publisher_url, timeout_sec=timeout_sec)
        series = parser(text)
        cache_path.write_text(text, encoding="utf-8")
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
    value_col = next(
        (c for c in frame.columns if c.lower() in {"ofr_fsi", "fsi", "obs_value", "value"}),
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


_PARSERS: dict[str, Callable[[str], pd.Series]] = {
    "CISS": _parse_ciss_csv,
    "SRISK": _parse_srisk_csv,
    "COVAR": _parse_covar_csv,
    "OFR_FSI": _parse_ofr_fsi_csv,
}


__all__ = [
    "CISS",
    "COVAR",
    "KNOWN_INDICATORS",
    "ManualDownloadRequired",
    "OFR_FSI",
    "SRISK",
    "ExternalIndicator",
    "external_series_to_long_panel",
    "fetch_all_external",
    "fetch_external_indicator",
    "write_template_csv",
]
