from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from harvester.core.manifest import build_manifest
from harvester.core.provenance import build_provenance
from harvester.providers import ProviderError, build_provider

logger = logging.getLogger(__name__)

OFFICIAL_SERIES_MAP: dict[str, dict[str, Any]] = {
    "fred": {
        "series": [
            "T10Y2Y", "DFF", "TEDRATE", "BAMLH0A0HYM2", "VIXCLS",
            # M channel — funding / transmission
            "SOFR", "DCPF3M", "DGS3MO", "DPRIME", "IORB",
            # D channel — depth / deformation
            "BAMLC0A0CM", "BAMLC0A4CBBB", "DBAA", "DAAA", "BAA10YM",
            # cross-channel benchmarks
            "STLFSI4",
            # NFCI sub-indices
            "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE",
        ],
        "desc": {
            "T10Y2Y": "10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity",
            "DFF": "Federal Funds Effective Rate",
            "TEDRATE": "TED Spread",
            "BAMLH0A0HYM2": "ICE BofA US High Yield Index Option-Adjusted Spread",
            "VIXCLS": "CBOE Volatility Index: VIX",
            "SOFR": "Secured Overnight Financing Rate",
            "DCPF3M": "3-Month AA Financial Commercial Paper Rate",
            "DGS3MO": "3-Month Treasury Constant Maturity Rate",
            "DPRIME": "Bank Prime Loan Rate",
            "IORB": "Interest Rate on Reserve Balances",
            "BAMLC0A0CM": "ICE BofA US Corporate Index Option-Adjusted Spread",
            "BAMLC0A4CBBB": "ICE BofA BBB US Corporate Index Option-Adjusted Spread",
            "DBAA": "Moody's Seasoned Baa Corporate Bond Yield",
            "DAAA": "Moody's Seasoned Aaa Corporate Bond Yield",
            "BAA10YM": "Moody's Seasoned Baa Corporate Bond Yield Relative to 10-Year Treasury",
            "STLFSI4": "St. Louis Fed Financial Stress Index",
            "NFCIRISK": "Chicago Fed NFCI Risk Subindex",
            "NFCICREDIT": "Chicago Fed NFCI Credit Subindex",
            "NFCILEVERAGE": "Chicago Fed NFCI Leverage Subindex",
        },
    },
    "h41": {
        "series": ["discount_window", "primary_credit", "btfp"],
        "desc": {
            "discount_window": "Discount Window Borrowing (direct H.4.1 DDP CSV; FRED fallback available)",
            "primary_credit": "Primary Credit (direct H.4.1 DDP CSV; FRED fallback available)",
            "btfp": "Bank Term Funding Program (direct H.4.1 DDP CSV; observed_zero post-expiry)",
        },
    },
    "treasury": {
        "series": [
            "debt_to_penny:tot_pub_debt_out_amt",
            "daily_treasury_statement:open_today_bal",
        ],
        "desc": {
            "debt_to_penny:tot_pub_debt_out_amt": "Total Public Debt Outstanding",
            "daily_treasury_statement:open_today_bal": "Opening Balance Today",
        },
    },
    "sec": {
        "series": ["0000072971"],
        "desc": {
            "0000072971": (
                "Issuer filing pulse — daily EDGAR filing count for CIK 0000072971. "
                "This is a filing_count proxy (coarse), NOT a credit-stress or "
                "risk-exposure metric.  Intended as a first-round verifiability "
                "pulse for downstream shadow-pressure interpretation."
            ),
        },
    },
    "openbb_fred": {
        "series": [
            "NFCI", "VIXCLS", "BAMLH0A0HYM2", "STLFSI4", "SOFR", "IORB",
            "DCPF3M", "DGS3MO", "DPRIME",
            "BAMLC0A0CM", "BAMLC0A4CBBB", "DBAA", "DAAA", "BAA10YM",
            "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE",
        ],
        "desc": {
            "NFCI": "Chicago Fed National Financial Conditions Index via OpenBB/FRED.",
            "VIXCLS": "CBOE Volatility Index via OpenBB/FRED.",
            "BAMLH0A0HYM2": "ICE BofA US High Yield OAS via OpenBB/FRED.",
            "STLFSI4": "St. Louis Fed Financial Stress Index via OpenBB/FRED.",
            "SOFR": "Secured Overnight Financing Rate via OpenBB/FRED.",
            "IORB": "Interest on Reserve Balances via OpenBB/FRED.",
            "DCPF3M": "3-Month AA Financial Commercial Paper Rate via OpenBB/FRED.",
            "DGS3MO": "3-Month Treasury Constant Maturity Rate via OpenBB/FRED.",
            "DPRIME": "Bank Prime Loan Rate via OpenBB/FRED.",
            "BAMLC0A0CM": "ICE BofA US Corporate Index OAS via OpenBB/FRED.",
            "BAMLC0A4CBBB": "ICE BofA BBB US Corporate Index OAS via OpenBB/FRED.",
            "DBAA": "Moody's Baa Corporate Bond Yield via OpenBB/FRED.",
            "DAAA": "Moody's Aaa Corporate Bond Yield via OpenBB/FRED.",
            "BAA10YM": "Baa-10Y Treasury Spread via OpenBB/FRED.",
            "NFCIRISK": "Chicago Fed NFCI Risk Subindex via OpenBB/FRED.",
            "NFCICREDIT": "Chicago Fed NFCI Credit Subindex via OpenBB/FRED.",
            "NFCILEVERAGE": "Chicago Fed NFCI Leverage Subindex via OpenBB/FRED.",
        },
    },
    "cboe_direct": {
        "series": ["MOVE", "TYVIX", "VXTLT", "VVIX", "SKEW", "VIX9D", "VIX3M", "VIX6M", "SPX"],
        "desc": {
            "MOVE": "Rates-volatility slot backed by current CBOE VXTLT direct CSV.",
            "TYVIX": "CBOE/ICE Interest Rate Volatility Index; historical file currently ends in 2023.",
            "VXTLT": "Cboe 20+ Year Treasury Bond ETF Volatility Index.",
            "VVIX": "CBOE VIX Volatility Index.",
            "SKEW": "CBOE SKEW Index.",
            "VIX9D": "CBOE 9-Day Volatility Index.",
            "VIX3M": "CBOE 3-Month Volatility Index.",
            "VIX6M": "CBOE 6-Month Volatility Index.",
            "SPX": "CBOE S&P 500 Index close.",
        },
    },
    "openbb_tiingo": {
        "series": ["HYG", "LQD", "TLT"],
        "desc": {
            "HYG": "iShares iBoxx High Yield Corporate Bond ETF daily close via OpenBB/Tiingo.",
            "LQD": "iShares iBoxx Investment Grade Corporate Bond ETF daily close via OpenBB/Tiingo.",
            "TLT": "iShares 20+ Year Treasury Bond ETF daily close via OpenBB/Tiingo.",
        },
    },
    "openbb_yfinance": {
        "series": ["SPY", "QQQ", "IWM", "DIA", "^SKEW", "^VVIX"],
        "desc": {
            "SPY": "SPDR S&P 500 ETF Trust daily close via OpenBB/yfinance.",
            "QQQ": "Invesco QQQ Trust (Nasdaq-100) daily close via OpenBB/yfinance.",
            "IWM": "iShares Russell 2000 ETF daily close via OpenBB/yfinance.",
            "DIA": "SPDR Dow Jones Industrial Average ETF daily close via OpenBB/yfinance.",
            "^SKEW": "CBOE SKEW Index — tail risk pricing in S&P 500 options. K channel proxy.",
            "^VVIX": "CBOE VVIX — volatility of VIX (vol-of-vol). K channel proxy.",
        },
    },
}

DEFAULT_OFFICIAL_PROVIDERS = [
    "fred",
    "h41",
    "treasury",
    "sec",
    "openbb_fred",
    "cboe_direct",
    "openbb_tiingo",
    "openbb_yfinance",
]


def data_root() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def _ensure_fred_api_key() -> None:
    """Set FRED_API_KEY from OpenBB settings if not already in environment."""
    if os.environ.get("FRED_API_KEY"):
        return
    candidates = [
        Path.cwd() / "OpenBB" / "settings.env",
        WorkspacePaths.discover().root / "OpenBB" / "settings.env",
    ]
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "OPENBB_FRED_API_KEY" and value:
                os.environ.setdefault("FRED_API_KEY", value)
                return


def fetch_official_series(
    *,
    as_of_date: str = "",
    data_root: str = "",
    providers: list[str] | None = None,
    cache: bool = True,
    api_keys: dict[str, str] | None = None,
) -> pd.DataFrame:
    _ensure_fred_api_key()
    dr = Path(data_root) if data_root else globals()["data_root"]()
    keys = api_keys or {}
    enabled: list[str]
    if providers is None:
        enabled = list(DEFAULT_OFFICIAL_PROVIDERS)
    else:
        enabled = list(providers)
    vintage = datetime.now(UTC).strftime("%Y-%m-%d")
    if not as_of_date:
        as_of_date = vintage

    all_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for provider_name in enabled:
        config = OFFICIAL_SERIES_MAP.get(provider_name)
        if config is None:
            errors.append({"provider": provider_name, "error": "unknown provider"})
            continue

        series_list = list(config["series"])
        try:
            provider_kwargs: dict[str, Any] = {
                "api_key": keys.get(provider_name, ""),
                "data_root": str(dr) if dr else "",
                "cache": cache,
            }
            if provider_name.startswith("openbb"):
                provider_kwargs["settings_env"] = keys.get("openbb_settings_env", "")
            prov = build_provider(
                provider_name,
                **provider_kwargs,
            )
        except ProviderError as exc:
            errors.append({"provider": provider_name, "error": str(exc)})
            continue

        results = prov.fetch_series(series_list)
        for r in results:
            if r.frame is not None and not r.frame.empty:
                df = r.frame.copy()
                if "source_id" not in df.columns:
                    df["source_id"] = r.provider or prov.source_id
                if "source_series_id" not in df.columns:
                    df["source_series_id"] = r.series_id
                if "series_id" not in df.columns:
                    df["series_id"] = (
                        df["source_id"].astype(str).str.upper()
                        + ":"
                        + df["source_series_id"].astype(str)
                    )
                for col in ["unit", "frequency"]:
                    if col not in df.columns:
                        df[col] = ""
                df["vintage_date"] = vintage
                qf = 0
                if r.fetch_error:
                    qf = 2
                elif r.fetch_fallback_reason:
                    qf = 1
                df["quality_flag"] = qf
                needed = [
                    c for c in
                    ["date", "series_id", "source_id", "source_series_id",
                     "value", "unit", "frequency", "vintage_date", "quality_flag"]
                    if c in df.columns
                ]
                all_results.append(df[needed])
            else:
                errors.append({
                    "provider": provider_name,
                    "series_id": r.series_id,
                    "error": r.fetch_error or "unknown",
                    "fallback_reason": r.fetch_fallback_reason,
                })

    if not all_results:
        logger.warning("fetch_official_series: no data returned from any provider")
        return pd.DataFrame(columns=[
            "date", "series_id", "source_id", "source_series_id",
            "value", "unit", "frequency", "vintage_date", "quality_flag",
        ])

    panel = pd.concat(all_results, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["series_id", "date"]).reset_index(drop=True)
    return panel


def save_processed_panel(panel: pd.DataFrame, data_root: str = "") -> Path:
    dr = Path(data_root) if data_root else globals()["data_root"]()
    processed_dir = dr / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    path = processed_dir / "official_panel.parquet"
    panel.to_parquet(path, index=False)
    return path


def make_manifest(
    *,
    dataset_id: str,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    data_path: Path,
    provider: str,
    source_url: str,
    source_params: dict[str, Any] | None = None,
    columns: list[dict[str, Any]] | None = None,
    provenance_path: str = "",
    quality_report_path: str | None = None,
    row_count: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    file_bytes = data_path.read_bytes()
    sha = hashlib.sha256(file_bytes).hexdigest()
    size = len(file_bytes)

    if not columns:
        columns = _default_columns()

    prov_path = provenance_path or f"provenance/{dataset_id}.provenance.json"

    date_start = _date_min(data_path)
    if not date_start:
        date_start = as_of_date

    return build_manifest(
        dataset_id=dataset_id,
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        source={
            "provider": provider,
            "kind": "public_api",
            "url_or_reference": source_url,
            "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
        data_file={
            "path": f"data/{data_path.name}",
            "format": "parquet",
            "sha256": sha,
            "byte_size": size,
            "row_count": row_count,
        },
        columns=columns,
        time_coverage={
            "start": date_start,
            "end": as_of_date,
            "frequency": "irregular",
            "time_column": "date",
        },
        provenance_path=prov_path,
        quality_report_path=quality_report_path,
        notes=notes,
    )


def make_provenance(
    *,
    dataset_id: str,
    release_id: str,
    method: str,
    source_identifier: str,
    source_params: dict[str, Any] | None = None,
    final_sha256: str,
    raw_sha256: str = "",
    notes: str = "",
) -> dict[str, Any]:
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    acquisition: dict[str, Any] = {
        "method": method,
        "source_identifier": source_identifier,
        "started_at": ts,
        "completed_at": ts,
        "operator": "harvester.official",
    }
    checksums: dict[str, str] = {"final_sha256": final_sha256}
    if raw_sha256 and len(raw_sha256) == 64:
        checksums["raw_sha256"] = raw_sha256

    return build_provenance(
        dataset_id=dataset_id,
        release_id=release_id,
        acquisition=acquisition,
        checksums=checksums,
        notes=notes,
    )


def stage_release(
    panel: pd.DataFrame,
    *,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    exports_root: str = "",
    notes: str = "",
) -> dict[str, Any]:
    ex_root = Path(exports_root) if exports_root else data_root() / "exports"
    release_dir = ex_root / release_id

    for sub in ("data", "manifests", "provenance"):
        (release_dir / sub).mkdir(parents=True, exist_ok=True)

    data_path = release_dir / "data" / "official_panel.parquet"
    panel.to_parquet(data_path, index=False)

    columns = _default_columns()
    manifest = make_manifest(
        dataset_id="official_panel",
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        data_path=data_path,
        provider="harvester.official",
        source_url=OFFICIAL_SERIES_MAP.get("fred", {}).get("_url", "https://api.stlouisfed.org/fred"),
        columns=columns,
        provenance_path="provenance/official_panel.provenance.json",
        row_count=len(panel),
        notes=notes or (
            "Official public data panel aggregated from FRED, Treasury FiscalData, "
            "SEC EDGAR, and H.4.1 direct DDP CSV. "
            "SEC filing_pulse is a coarse filing_count proxy, NOT a credit-stress or risk-exposure metric. "
            "BTFP values of zero post-expiry are observed_zero (data quality OK, not an error)."
        ),
    )

    import json as _json
    manifest_path = release_dir / "manifests" / "official_panel.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    provenance = make_provenance(
        dataset_id="official_panel",
        release_id=release_id,
        method="api_client",
        source_identifier="harvester.providers (fred, treasury, sec, h41)",
        final_sha256=manifest["data_file"]["sha256"],
        raw_sha256="",
        notes=notes or "Aggregated official data from multiple public sources.",
    )

    prov_path = release_dir / "provenance" / "official_panel.provenance.json"
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(_json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "release_id": release_id,
        "release_dir": str(release_dir),
        "data_path": str(data_path),
        "manifest_path": str(manifest_path),
        "provenance_path": str(prov_path),
        "row_count": len(panel),
    }


def _default_columns() -> list[dict[str, Any]]:
    return [
        {"name": "date", "dtype": "date", "nullable": False,
         "description": "Observation date.", "semantic_role": "time_index"},
        {"name": "series_id", "dtype": "string", "nullable": False,
         "description": "Full series identifier (e.g. FRED:T10Y2Y).", "semantic_role": "identifier"},
        {"name": "source_id", "dtype": "string", "nullable": False,
         "description": "Source provider (fred, treasury, sec, h41).", "semantic_role": "category"},
        {"name": "source_series_id", "dtype": "string", "nullable": False,
         "description": "Raw series identifier from source.", "semantic_role": "identifier"},
        {"name": "value", "dtype": "float64", "nullable": True,
         "description": "Observed value.", "semantic_role": "measure"},
        {"name": "unit", "dtype": "string", "nullable": True,
         "description": "Unit of measurement.", "semantic_role": "metadata"},
        {"name": "frequency", "dtype": "string", "nullable": True,
         "description": "Sampling frequency.", "semantic_role": "metadata"},
        {"name": "vintage_date", "dtype": "date", "nullable": True,
         "description": "Date the data was observed/retrieved.", "semantic_role": "metadata"},
        {"name": "quality_flag", "dtype": "string", "nullable": False,
         "description": "Quality label such as observed, fallback, error, derived, synthetic_proxy, or missing.", "semantic_role": "metadata"},
    ]


def _date_min(path: Path) -> str:
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return ""
        dates = pd.to_datetime(df["date"])
        if dates.empty:
            return ""
        return dates.min().strftime("%Y-%m-%d")
    except Exception:
        return ""


# ======================================================================
# Registry-based acquisition (Phase C)
# ======================================================================


def fetch_official_series_from_registry(
    *,
    as_of_date: str = "",
    data_root: str = "",
    providers: list[str] | None = None,
    cache: bool = True,
    api_keys: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Fetch all active series from the YAML registry.

    Uses provider_priority to route each series through its primary provider.
    Returns a canonical benchmark_panel in long format.
    """
    from harvester.registry import RegistrySeries, load_registry

    _ensure_fred_api_key()
    registry = load_registry()
    dr = Path(data_root) if data_root else globals()["data_root"]()
    keys = api_keys or {}
    vintage = datetime.now(UTC).strftime("%Y-%m-%d")
    if not as_of_date:
        as_of_date = vintage

    # Determine which providers to use
    enabled: set[str]
    if providers is not None:
        enabled = set(providers)
    else:
        enabled = set(DEFAULT_OFFICIAL_PROVIDERS)

    # Build provider → series mapping from registry
    provider_series: dict[str, list[RegistrySeries]] = {}
    for s in registry.active_series():
        if s.is_derived:
            continue
        for p in s.provider_priority:
            if p in enabled:
                provider_series.setdefault(p, []).append(s)
                break

    all_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for provider_name in sorted(provider_series.keys()):
        series_list = provider_series[provider_name]
        try:
            provider_kwargs: dict[str, Any] = {
                "api_key": keys.get(provider_name, ""),
                "data_root": str(dr) if dr else "",
                "cache": cache,
            }
            if provider_name.startswith("openbb"):
                provider_kwargs["settings_env"] = keys.get("openbb_settings_env", "")
            prov = build_provider(provider_name, **provider_kwargs)
        except ProviderError as exc:
            errors.append({"provider": provider_name, "error": str(exc)})
            continue

        source_series_ids = [s.source_series_id or s.canonical_id for s in series_list]
        results = prov.fetch_series(source_series_ids)
        for r in results:
            if r.frame is not None and not r.frame.empty:
                df = r.frame.copy()
                if "source_id" not in df.columns:
                    df["source_id"] = r.provider or prov.source_id
                if "source_series_id" not in df.columns:
                    df["source_series_id"] = r.series_id
                if "series_id" not in df.columns:
                    df["series_id"] = (
                        df["source_id"].astype(str).str.upper()
                        + ":"
                        + df["source_series_id"].astype(str)
                    )
                for col in ["unit", "frequency"]:
                    if col not in df.columns:
                        df[col] = ""
                df["vintage_date"] = vintage
                qf = 0
                if r.fetch_error:
                    qf = 2
                elif r.fetch_fallback_reason:
                    qf = 1
                df["quality_flag"] = qf
                needed = [
                    c for c in
                    ["date", "series_id", "source_id", "source_series_id",
                     "value", "unit", "frequency", "vintage_date", "quality_flag"]
                    if c in df.columns
                ]
                all_results.append(df[needed])
            else:
                errors.append({
                    "provider": provider_name,
                    "series_id": r.series_id,
                    "error": r.fetch_error or "unknown",
                    "fallback_reason": r.fetch_fallback_reason,
                })

    if not all_results:
        logger.warning("fetch_official_series_from_registry: no data returned")
        return pd.DataFrame(columns=[
            "date", "series_id", "source_id", "source_series_id",
            "value", "unit", "frequency", "vintage_date", "quality_flag",
        ])

    panel = pd.concat(all_results, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["series_id", "date"]).reset_index(drop=True)
    return panel


def build_complete_benchmark_panel(
    acquired: pd.DataFrame,
    *,
    external_indicators: pd.DataFrame | None = None,
    derived_panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine acquired series, external indicators, and derived series into one panel."""
    pieces = [acquired]
    if external_indicators is not None and not external_indicators.empty:
        pieces.append(external_indicators)
    if derived_panel is not None and not derived_panel.empty:
        pieces.append(derived_panel)
    if len(pieces) == 1:
        return normalize_release_panel(acquired)
    combined = pd.concat(pieces, ignore_index=True)
    combined = combined.sort_values(["series_id", "date"]).reset_index(drop=True)
    return normalize_release_panel(combined)


def normalize_release_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Normalize mixed acquired/derived panels before release serialization."""
    out = panel.copy()
    if "quality_flag" in out:
        out["quality_flag"] = out["quality_flag"].map(_quality_flag_label).astype("string")
    for column in ("series_id", "source_id", "source_series_id", "unit", "frequency", "vintage_date"):
        if column in out:
            out[column] = out[column].astype(str)
    if "value" in out:
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
    if "date" in out:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    return out


def _quality_flag_label(value: Any) -> str:
    if value in {0, "0", "ok"}:
        return "observed"
    if value in {1, "1"}:
        return "fallback"
    if value in {2, "2"}:
        return "error"
    if value in {None, ""}:
        return "unknown"
    return str(value)


def build_proxy_candidate_panel(
    derived_panel: pd.DataFrame,
    *,
    acquired: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build proxy_candidate_panel from derived series.

    Includes TEDRATE replacements, volatility term structure, Roll spread,
    and legacy synthetic MOVE proxy.
    """
    proxy_ids = {
        "SOFR_IORB_SPREAD",
        "CP_TBILL_SPREAD",
        "VIX3M_VIX_SLOPE",
        "SPX_ROLL_SPREAD",
        "MOVE_PROXY",
    }
    candidates = derived_panel[derived_panel["source_series_id"].isin(proxy_ids)].copy()
    return candidates.sort_values(["series_id", "date"]).reset_index(drop=True)


def panel_identity_set(panel: pd.DataFrame) -> set[str]:
    """Return all canonical and provider-native identifiers visible in a panel."""
    identifiers: set[str] = set()
    if panel.empty:
        return identifiers
    if "series_id" in panel:
        for value in panel["series_id"].dropna().astype(str):
            identifiers.add(value)
            if ":" in value:
                identifiers.add(value.split(":", 1)[1])
    if "source_series_id" in panel:
        identifiers.update(panel["source_series_id"].dropna().astype(str))
    return identifiers


def stage_complete_release(
    *,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    exports_root: str = "",
    providers: list[str] | None = None,
    cache: bool = True,
    api_keys: dict[str, str] | None = None,
    include_external: bool = True,
    notes: str = "",
) -> dict[str, Any]:
    """Stage a complete Harvester release with registry-driven acquisition.

    This is the Phase C entry point that:
    1. Fetches all active series from the registry
    2. Builds derived series (TEDRATE replacements, MOVE_PROXY if needed)
    3. Optionally includes external indicators (OFR_FSI, etc.)
    4. Writes complete manifest and provenance for each panel
    5. Writes corpus_index status

    Returns a dict with release metadata suitable for finalization.
    """
    from harvester.derived import (
        build_derived_manifest,
        build_derived_panel,
        build_derived_provenance,
    )
    from harvester.quality import build_quality_report, write_quality_report
    from harvester.registry import load_registry

    registry = load_registry()
    if not vintage_date:
        vintage_date = datetime.now(UTC).strftime("%Y-%m-%d")
    if not as_of_date:
        as_of_date = vintage_date
    ex_root = Path(exports_root) if exports_root else data_root() / "exports"
    release_dir = ex_root / release_id

    for sub in ("data", "manifests", "provenance", "quality_reports"):
        (release_dir / sub).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Fetch acquired series
    # ------------------------------------------------------------------
    panel = fetch_official_series_from_registry(
        as_of_date=as_of_date,
        data_root=str(data_root()),
        providers=providers,
        cache=cache,
        api_keys=api_keys,
    )

    # ------------------------------------------------------------------
    # 2. Build derived series
    # ------------------------------------------------------------------
    derived_series = registry.derived_series()
    derived_panel = build_derived_panel(
        list(derived_series),
        panel,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
    )

    # ------------------------------------------------------------------
    # 3. External indicators (OFR_FSI)
    # ------------------------------------------------------------------
    ext_panel = pd.DataFrame()
    if include_external:
        try:
            from harvester.providers.external_indicators import (
                KNOWN_INDICATORS,
                ManualDownloadRequired,
                external_series_to_long_panel,
                fetch_external_indicator,
            )
            ext_results: dict[str, pd.Series] = {}
            for indicator in KNOWN_INDICATORS:
                cache_dir = data_root() / "raw" / "external_indicators"
                cache_dir.mkdir(parents=True, exist_ok=True)
                try:
                    result = fetch_external_indicator(indicator, cache_dir=cache_dir, refresh=False, timeout_sec=30)
                except ManualDownloadRequired as exc:
                    logger.warning("external indicator unavailable: %s", exc)
                    continue
                if result is not None and not result.empty:
                    ext_results[indicator.series_id] = result
            if ext_results:
                ext_panel = external_series_to_long_panel(ext_results, vintage_date=vintage_date)
        except Exception:
            logger.warning("external indicator fetch failed", exc_info=True)

    # ------------------------------------------------------------------
    # 4. Combine into benchmark_panel and proxy_candidate_panel
    # ------------------------------------------------------------------
    benchmark = build_complete_benchmark_panel(
        panel,
        external_indicators=ext_panel if not ext_panel.empty else None,
        derived_panel=derived_panel,
    )
    proxy_candidates = build_proxy_candidate_panel(derived_panel)

    # ------------------------------------------------------------------
    # 5. Write benchmark_panel
    # ------------------------------------------------------------------
    bench_path = release_dir / "data" / "benchmark_panel.parquet"
    benchmark.to_parquet(bench_path, index=False)
    bench_sha = hashlib.sha256(bench_path.read_bytes()).hexdigest()
    bench_size = bench_path.stat().st_size

    panel_dates = pd.to_datetime(benchmark["date"])
    bench_manifest = make_manifest(
        dataset_id="benchmark_panel",
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        data_path=bench_path,
        provider="harvester.complete",
        source_url="registry:configs/series_registry.yaml",
        columns=_default_columns(),
        provenance_path="provenance/benchmark_panel.provenance.json",
        quality_report_path="quality_reports/benchmark_panel.quality.json",
        row_count=len(benchmark),
        notes=notes or "Complete benchmark panel: acquired + derived + external indicators.",
    )
    bench_manifest["data_file"]["sha256"] = bench_sha
    bench_manifest["data_file"]["byte_size"] = bench_size
    if not panel_dates.empty and panel_dates.notna().any():
        bench_manifest["time_coverage"]["start"] = panel_dates.min().strftime("%Y-%m-%d")
        bench_manifest["time_coverage"]["end"] = panel_dates.max().strftime("%Y-%m-%d")

    manifest_path = release_dir / "manifests" / "benchmark_panel.manifest.json"
    manifest_path.write_text(json.dumps(bench_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    bench_prov = make_provenance(
        dataset_id="benchmark_panel",
        release_id=release_id,
        method="api_client",
        source_identifier="harvester.registry + derived + external_indicators",
        final_sha256=bench_sha,
        notes=notes or "Aggregated from registry-defined providers + derived computations.",
    )
    (release_dir / "provenance" / "benchmark_panel.provenance.json").write_text(
        json.dumps(bench_prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_quality_report(
        build_quality_report(
            "benchmark_panel",
            benchmark,
            as_of_date=as_of_date,
            required_columns=["date", "series_id", "source_id", "source_series_id", "value"],
        ),
        release_dir,
        "benchmark_panel",
    )

    # ------------------------------------------------------------------
    # 6. Write proxy_candidate_panel (or document emptiness)
    # ------------------------------------------------------------------
    proxy_path = release_dir / "data" / "proxy_candidate_panel.parquet"
    if not proxy_candidates.empty:
        proxy_candidates.to_parquet(proxy_path, index=False)
    else:
        # Write an empty parquet with the right schema
        pd.DataFrame(columns=[
            "date", "series_id", "source_id", "source_series_id",
            "value", "unit", "frequency", "vintage_date", "quality_flag",
        ]).to_parquet(proxy_path, index=False)

    proxy_sha = hashlib.sha256(proxy_path.read_bytes()).hexdigest()
    proxy_size = proxy_path.stat().st_size
    proxy_row_count = len(proxy_candidates)

    proxy_manifest = make_manifest(
        dataset_id="proxy_candidate_panel",
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        data_path=proxy_path,
        provider="harvester.derived",
        source_url="registry:configs/series_registry.yaml",
        columns=_default_columns(),
        provenance_path="provenance/proxy_candidate_panel.provenance.json",
        quality_report_path="quality_reports/proxy_candidate_panel.quality.json",
        row_count=proxy_row_count,
        notes="Derived TEDRATE replacement proxies and synthetic series. "
              "Not canonical input — available for Deformation routing.",
    )
    proxy_manifest["data_file"]["sha256"] = proxy_sha
    proxy_manifest["data_file"]["byte_size"] = proxy_size

    (release_dir / "manifests" / "proxy_candidate_panel.manifest.json").write_text(
        json.dumps(proxy_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    proxy_prov = make_provenance(
        dataset_id="proxy_candidate_panel",
        release_id=release_id,
        method="computed",
        source_identifier="harvester.derived",
        final_sha256=proxy_sha,
        notes="Derived proxy series for Deformation routing.",
    )
    (release_dir / "provenance" / "proxy_candidate_panel.provenance.json").write_text(
        json.dumps(proxy_prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_quality_report(
        build_quality_report(
            "proxy_candidate_panel",
            proxy_candidates,
            as_of_date=as_of_date,
            required_columns=["date", "series_id", "source_id", "source_series_id", "value"],
            allow_empty=True,
        ),
        release_dir,
        "proxy_candidate_panel",
    )

    # ------------------------------------------------------------------
    # 6b. Cross-asset ETF panel (Harvester evidence bundle)
    # ------------------------------------------------------------------
    from harvester.cross_asset_panel import stage_cross_asset_panel

    cross_asset_info = stage_cross_asset_panel(
        release_dir,
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        # CLI is normally launched from packages/harvester; derive the shared
        # System workspace from the canonical data root so history is merged
        # from /System/Data rather than an accidental package-local /Data.
        workspace=data_root().resolve().parents[1],
    )

    # ------------------------------------------------------------------
    # 7. Write corpus_index status
    # ------------------------------------------------------------------
    corpus_status = {
        "panel": "corpus_index",
        "status": "disabled",
        "reason": "narrative corpus not part of current Phase C release",
        "release_id": release_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    corpus_path = release_dir / "data" / "corpus_index.parquet"
    corpus_columns = [
        {"name": "doc_id", "dtype": "string", "nullable": False,
         "description": "Stable document identifier.", "semantic_role": "primary_key"},
        {"name": "date", "dtype": "date", "nullable": True,
         "description": "Document publication date when known.", "semantic_role": "time_index"},
        {"name": "source", "dtype": "string", "nullable": True,
         "description": "Document source.", "semantic_role": "category"},
        {"name": "text_snippet", "dtype": "string", "nullable": True,
         "description": "Short preview text for audit indexing.", "semantic_role": "metadata"},
    ]
    pd.DataFrame(columns=[c["name"] for c in corpus_columns]).to_parquet(corpus_path, index=False)
    corpus_sha = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    corpus_size = corpus_path.stat().st_size
    corpus_manifest = build_manifest(
        dataset_id="corpus_index",
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        source={
            "provider": "harvester.corpus",
            "kind": "internal_corpus",
            "url_or_reference": "data/corpus",
            "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "access_notes": corpus_status["reason"],
        },
        data_file={
            "path": "data/corpus_index.parquet",
            "format": "parquet",
            "sha256": corpus_sha,
            "byte_size": corpus_size,
            "row_count": 0,
        },
        columns=corpus_columns,
        time_coverage={
            "start": as_of_date,
            "end": as_of_date,
            "frequency": "irregular",
            "time_column": "date",
        },
        provenance_path="provenance/corpus_index.provenance.json",
        quality_report_path="quality_reports/corpus_index.quality.json",
        notes=f"{corpus_status['status']}: {corpus_status['reason']}",
    )
    (release_dir / "manifests" / "corpus_index.manifest.json").write_text(
        json.dumps(corpus_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    corpus_prov = make_provenance(
        dataset_id="corpus_index",
        release_id=release_id,
        method="computed",
        source_identifier="harvester.corpus disabled status",
        final_sha256=corpus_sha,
        notes=f"{corpus_status['status']}: {corpus_status['reason']}",
    )
    (release_dir / "provenance" / "corpus_index.provenance.json").write_text(
        json.dumps(corpus_prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_quality_report(
        build_quality_report(
            "corpus_index",
            pd.DataFrame(columns=[c["name"] for c in corpus_columns]),
            as_of_date=as_of_date,
            required_columns=["doc_id", "date", "source", "text_snippet"],
            allow_empty=True,
        ),
        release_dir,
        "corpus_index",
    )

    # ------------------------------------------------------------------
    # 8. Run promotion gate on staged release
    # ------------------------------------------------------------------
    from harvester.promotion import run_promotion_gate, write_gate_report

    panel_ids = panel_identity_set(benchmark)
    gate_result = run_promotion_gate(
        release_dir,
        registry,
        panel_series_ids=panel_ids,
        sha256_verified=True,
        empty_panels=["corpus_index"] if proxy_row_count == 0 else [],
        cross_asset_row_count=int(cross_asset_info.get("row_count", 0)),
        cross_asset_symbol_count=int(cross_asset_info.get("symbol_count", 0)),
    )
    write_gate_report(gate_result, release_id, release_dir)

    return {
        "release_id": release_id,
        "release_dir": str(release_dir),
        "benchmark_path": str(bench_path),
        "proxy_path": str(proxy_path),
        "cross_asset_path": cross_asset_info.get("data_path"),
        "benchmark_rows": len(benchmark),
        "proxy_rows": proxy_row_count,
        "cross_asset_rows": cross_asset_info.get("row_count", 0),
        "derived_series": [s.canonical_id for s in derived_series],
        "gate_state": gate_result.state,
        "gate_passed": gate_result.passed,
        "gate_blockers": gate_result.blockers,
        "gate_warnings": gate_result.warnings,
    }
