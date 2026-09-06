from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from harvester.core.acquisition_timing import (
    replace_local_steps,
    source_record,
    track_local_step,
    utc_now,
)
from harvester.core.exporter import resolve_release_dir, validate_release_id
from harvester.core.manifest import build_manifest
from harvester.core.observation import (
    observation_coverage_from_frame,
    read_observation_coverage,
)
from harvester.core.provenance import build_provenance
from harvester.providers import ProviderError, build_provider, openbb_available
from system_runtime.paths import WorkspacePaths

logger = logging.getLogger(__name__)


# These series are acquired by ``providers.external_indicators`` below rather
# than by the generic provider adapter loop.  Keeping them out of the generic
# loop avoids reporting a false provider failure (``external_public`` and the
# OFR aliases are orchestration labels, not ``build_provider`` implementations).
_EXTERNAL_MANAGED_PROVIDER_PRIORITIES = frozenset(
    {"external_public", "direct_ofr", "openbb_if_available"}
)


def _is_external_managed_series(series: Any) -> bool:
    return bool(
        set(getattr(series, "provider_priority", ()) or ())
        & _EXTERNAL_MANAGED_PROVIDER_PRIORITIES
    )


def _external_indicator_timeout_seconds() -> int:
    """Return the bounded timeout for optional publisher feeds.

    These feeds are diagnostic/secondary inputs.  A stalled publisher must
    not consume the whole daily-run budget while the primary registry path is
    still able to produce a governed release candidate.
    """
    raw = os.environ.get("HARVESTER_EXTERNAL_TIMEOUT_SEC", "10").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 10
    return max(1, min(value, 30))

OFFICIAL_SERIES_MAP: dict[str, dict[str, Any]] = {
    "fred": {
        "series": [
            "T10Y2Y", "DFF", "TEDRATE", "BAMLH0A0HYM2", "VIXCLS",
            # Policy and funding rates (SOFR, CP, T-bill, prime, IORB)
            "SOFR", "DCPF3M", "DGS3MO", "DPRIME", "IORB",
            # Credit and funding-path spreads (ICE BofA OAS, Moody's Baa/Aaa)
            "BAMLC0A0CM", "BAMLC0A4CBBB", "DBAA", "DAAA", "BAA10YM",
            # cross-channel benchmarks
            "STLFSI4",
            # NFCI sub-indices
            "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE",
            # Shadow leverage / liquidity (proxy catalog)
            "RRPONTSYD", "WRESBAL", "WTREGEN",
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
            "RRPONTSYD": "Overnight Reverse Repurchase Agreements",
            "WRESBAL": "Reserve Balances with Federal Reserve Banks",
            "WTREGEN": "Treasury General Account balance",
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
    "etf_provider_chain": {
        "series": ["SPY", "QQQ", "IWM", "DIA", "HYG", "LQD", "TLT"],
        "desc": {
            "SPY": "SPDR S&P 500 ETF Trust daily close via Tiingo/Massive/yfinance chain.",
            "QQQ": "Invesco QQQ Trust daily close via Tiingo/Massive/yfinance chain.",
            "IWM": "iShares Russell 2000 ETF daily close via Tiingo/Massive/yfinance chain.",
            "DIA": "SPDR Dow Jones Industrial Average ETF daily close via Tiingo/Massive/yfinance chain.",
            "HYG": "iShares iBoxx High Yield Corporate Bond ETF daily close via Tiingo/Massive/yfinance chain.",
            "LQD": "iShares iBoxx Investment Grade Corporate Bond ETF daily close via Tiingo/Massive/yfinance chain.",
            "TLT": "iShares 20+ Year Treasury Bond ETF daily close via Tiingo/Massive/yfinance chain.",
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
    "etf_provider_chain",
]

OFFICIAL_PROVIDER_OUTCOME_STATUSES = {
    "refreshed",
    "reused_same_content",
    "reused_after_provider_failure",
    "partial_provider_success",
    "provider_failed_no_acceptable_fallback",
    "no_release_expected",
    "environmentally_blocked",
}


def _provider_outcome(
    *,
    status: str,
    provider: str,
    requested_count: int,
    succeeded_count: int,
    failed_series: list[str] | None = None,
    fallback_reason: str = "",
    error: str = "",
    providers_used: list[str] | None = None,
    series_providers: dict[str, str] | None = None,
    series_attempts: dict[str, Any] | None = None,
    series_source_signatures: dict[str, Any] | None = None,
    provider_chain: list[str] | None = None,
    fallback_used: bool = False,
) -> dict[str, Any]:
    """Build the shared, schema-constrained acquisition outcome payload."""
    if status not in OFFICIAL_PROVIDER_OUTCOME_STATUSES:
        raise ValueError(f"unsupported provider outcome status: {status}")
    failed = sorted(set(failed_series or []))
    outcome: dict[str, Any] = {
        "status": status,
        "provider": provider or "unknown",
        "requested_count": int(requested_count),
        "succeeded_count": int(succeeded_count),
        "failed_count": len(failed),
        "failed_series": failed,
        "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if fallback_reason:
        outcome["fallback_reason"] = fallback_reason[:2000]
    if error:
        outcome["error"] = error[:2000]
    if providers_used:
        outcome["providers_used"] = sorted(set(str(item) for item in providers_used))
    if series_providers:
        outcome["series_providers"] = {
            str(key): str(value) for key, value in sorted(series_providers.items())
        }
    if series_attempts:
        outcome["series_attempts"] = {
            str(key): value for key, value in sorted(series_attempts.items())
        }
    if series_source_signatures:
        outcome["series_source_signatures"] = {
            str(key): value for key, value in sorted(series_source_signatures.items())
        }
    if provider_chain:
        outcome["provider_chain"] = [str(item) for item in provider_chain]
    if fallback_used:
        outcome["fallback_used"] = True
    # ETF parity is a cross-asset panel concern.  The generic benchmark
    # outcome is intentionally mixed-source (FRED, H.4.1, Treasury, SEC,
    # external indicators, and sometimes Tiingo ETF rows); applying the ETF
    # route classifier to that whole outcome incorrectly turns a healthy
    # benchmark release into a diagnostic-only route.
    outcome["availability"] = {
        "state": "STALE"
        if status in {"reused_same_content", "reused_after_provider_failure", "environmentally_blocked"}
        else "UNKNOWN",
        "calendar_status": "UNCONFIGURED",
        "available_at": None,
        "retrieved_at": outcome["retrieved_at"],
        "decision_usable": False,
        "reason": "publication_calendar_or_available_at_not_evidenced",
    }
    return outcome


def _failed_attempt_failure_classes(provider_outcome: dict[str, Any] | None) -> list[str]:
    """Extract normalized failed-attempt categories for downstream gates."""
    if not isinstance(provider_outcome, dict):
        return []
    series_attempts = provider_outcome.get("series_attempts")
    if not isinstance(series_attempts, dict):
        return []
    categories: set[str] = set()
    for attempts in series_attempts.values():
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict) or attempt.get("outcome") == "success":
                continue
            category = attempt.get("failure_class")
            if category:
                categories.add(str(category))
    return sorted(categories)


def _merge_external_provider_outcome(
    provider_outcome: dict[str, Any] | None,
    *,
    requested_series: set[str],
    succeeded_series: dict[str, str],
    failed_series: dict[str, str],
    manual_series: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Fold the separately acquired external indicators into one outcome.

    ``stage_complete_release`` intentionally has two acquisition paths: the
    generic registry adapter and the public-file/API external-indicator
    provider.  The release artifacts still need one provider outcome, but the
    counts must not double-count the external series or leave their generic
    adapter misses behind as false failures.
    """
    if not requested_series and not manual_series:
        return provider_outcome

    base = dict(provider_outcome or {})
    base_failed = {str(item) for item in base.get("failed_series", [])}
    combined_failed = base_failed | {str(item) for item in failed_series}
    base_requested = int(base.get("requested_count", 0) or 0)
    base_succeeded = int(base.get("succeeded_count", 0) or 0)
    combined_requested = base_requested + len(requested_series)
    combined_succeeded = base_succeeded + len(succeeded_series)
    if combined_requested == 0:
        status = "no_release_expected"
    elif combined_failed and combined_succeeded == 0:
        status = "provider_failed_no_acceptable_fallback"
    elif combined_failed:
        status = "partial_provider_success"
    else:
        status = "refreshed"

    merged: dict[str, Any] = {
        **base,
        "status": status,
        "provider": "harvester.complete",
        "requested_count": combined_requested,
        "succeeded_count": combined_succeeded,
        "failed_count": len(combined_failed),
        "failed_series": sorted(combined_failed),
        "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    providers_used = {
        str(item) for item in (base.get("providers_used") or []) if str(item).strip()
    }
    providers_used.update(str(item) for item in succeeded_series.values() if str(item).strip())
    if providers_used:
        merged["providers_used"] = sorted(providers_used)

    series_providers = {
        str(key): str(value)
        for key, value in (base.get("series_providers") or {}).items()
    }
    series_providers.update(
        {str(key): str(value) for key, value in succeeded_series.items()}
    )
    if series_providers:
        merged["series_providers"] = dict(sorted(series_providers.items()))

    errors: list[str] = []
    existing_error = str(base.get("error") or "").strip()
    if existing_error:
        errors.append(existing_error)
    if failed_series:
        external_errors = "; ".join(
            f"{series_id}: {failed_series[series_id]}"
            for series_id in sorted(failed_series)
        )
        errors.append(f"external indicator acquisition: {external_errors}")
    if errors:
        merged["error"] = "; ".join(errors)[:2000]
    else:
        merged.pop("error", None)

    if combined_failed:
        merged["fallback_reason"] = "some_requested_series_failed"
    else:
        merged.pop("fallback_reason", None)

    # Manual monthly sources are an explicit acquisition mode, not a failed
    # automated transport. Keep their state visible for operators without
    # putting them in failed_series/unavailable or changing the release gate.
    if manual_series:
        merged["manual_series"] = dict(sorted(manual_series.items()))
    else:
        merged.pop("manual_series", None)

    availability = dict(merged.get("availability") or {})
    availability["state"] = (
        "STALE"
        if status in {"reused_same_content", "reused_after_provider_failure", "environmentally_blocked"}
        else "UNKNOWN"
    )
    availability.setdefault("calendar_status", "UNCONFIGURED")
    availability.setdefault("available_at", None)
    availability.setdefault("decision_usable", False)
    availability.setdefault(
        "reason", "publication_calendar_or_available_at_not_evidenced"
    )
    availability["retrieved_at"] = merged["retrieved_at"]
    merged["availability"] = availability
    return merged


def prefer_openbb() -> bool:
    """Whether registry routing should try OpenBB providers before direct FRED.

    Env ``HARVESTER_PREFER_OPENBB``:
      auto (default) — True when the ``openbb`` package imports
      1/true/on      — force prefer
      0/false/off    — force direct-provider order from YAML
    """
    raw = os.environ.get("HARVESTER_PREFER_OPENBB", "auto").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return openbb_available()


def order_provider_priority(priority: list[str] | tuple[str, ...]) -> list[str]:
    """Put openbb_* providers first when prefer_openbb() is active."""
    items = list(priority)
    if not prefer_openbb():
        return items
    openbb_first = [p for p in items if str(p).startswith("openbb")]
    rest = [p for p in items if not str(p).startswith("openbb")]
    return openbb_first + rest


def data_root() -> Path:
    """Return the canonical workspace data root.

    The Harvester package is independently buildable, but a System checkout
    must never infer its data authority from the package's source location.
    The old ``parents[2] / data`` fallback pointed at
    ``packages/harvester/data`` and could make a real refresh acquire into a
    package-local shadow tree while publishing a release under canonical
    ``Data/harvester/exports``.
    """
    try:
        return WorkspacePaths.discover().data
    except (RuntimeError, OSError):
        # Standalone package tests may not have the System governance marker.
        # Keep that mode usable, but make the fallback explicit and isolated
        # from the canonical System path.
        return Path(__file__).resolve().parents[2] / "data"


def harvester_raw_root() -> Path:
    """Return the governed Harvester raw-data root.

    ``WorkspacePaths.data`` is the workspace-wide ``Data`` directory, while
    the Harvester raw/cache contract (and freshness registry) lives under
    ``Data/harvester/raw``.  Keeping this explicit prevents external
    indicators from being acquired into an unmonitored ``Data/raw`` shadow
    tree during the workspace migration.
    """
    try:
        return WorkspacePaths.discover().data / "harvester" / "raw"
    except (RuntimeError, OSError):
        return data_root() / "raw"


def workspace_root() -> Path:
    """Return the System checkout root, with the standalone fallback above."""
    try:
        return WorkspacePaths.discover().root
    except (RuntimeError, OSError):
        return data_root().parent


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
    observation_start: str | None = None,
    observation_end: str | None = None,
    provider_outcome: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    file_bytes = data_path.read_bytes()
    sha = hashlib.sha256(file_bytes).hexdigest()
    size = len(file_bytes)

    if not columns:
        columns = _default_columns()

    prov_path = provenance_path or f"provenance/{dataset_id}.provenance.json"
    actual_coverage = read_observation_coverage(
        data_path,
        file_format="parquet",
        time_column="date",
    )
    if actual_coverage is not None:
        actual_start = actual_coverage["start"]
        actual_end = actual_coverage["end"]
        if observation_start is not None and observation_start != actual_start:
            raise ValueError(
                f"manifest observation_start mismatch for {dataset_id}: "
                f"declared={observation_start}, actual={actual_start}"
            )
        if observation_end is not None and observation_end != actual_end:
            raise ValueError(
                f"manifest observation_end mismatch for {dataset_id}: "
                f"declared={observation_end}, actual={actual_end}"
            )
        observation_start = actual_start
        observation_end = actual_end

    return cast(dict[str, Any], build_manifest(
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
            "start": observation_start or as_of_date,
            "end": observation_end or as_of_date,
            "frequency": "irregular",
            "time_column": "date",
        },
        provenance_path=prov_path,
        quality_report_path=quality_report_path,
        provider_outcome=provider_outcome,
        notes=notes,
    ))


def make_provenance(
    *,
    dataset_id: str,
    release_id: str,
    method: str,
    source_identifier: str,
    source_params: dict[str, Any] | None = None,
    final_sha256: str,
    raw_sha256: str = "",
    provider_outcome: dict[str, Any] | None = None,
    observation_start: str | None = None,
    observation_end: str | None = None,
    observation_time_column: str = "date",
    availability: dict[str, Any] | None = None,
    integrity: dict[str, Any] | None = None,
    canonical_observation_path: str | None = None,
    canonical_observation_count: int | None = None,
    canonical_chain_path: str | None = None,
    canonical_chain_count: int | None = None,
    canonical_schema_version: str | None = None,
    canonical_lineage_path: str | None = None,
    previous_release_id: str | None = None,
    canonical_observation_delta_count: int | None = None,
    canonical_chain_delta_count: int | None = None,
    canonical_observation_merkle_root: str | None = None,
    canonical_chain_merkle_root: str | None = None,
    measurement_spec_path: str | None = None,
    measurement_spec_version: str | None = None,
    notes: str = "",
    acquisition_sources: list[dict[str, Any]] | None = None,
    local_steps: list[dict[str, Any]] | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    acquisition: dict[str, Any] = {
        "method": method,
        "source_identifier": source_identifier,
        "started_at": started_at or ts,
        "completed_at": completed_at or ts,
        "operator": "harvester.official",
    }
    if acquisition_sources is not None:
        acquisition["sources"] = list(acquisition_sources)
    if local_steps is not None:
        acquisition["local_steps"] = list(local_steps)
    checksums: dict[str, str] = {"final_sha256": final_sha256}
    if raw_sha256 and len(raw_sha256) == 64:
        checksums["raw_sha256"] = raw_sha256

    return cast(dict[str, Any], build_provenance(
        dataset_id=dataset_id,
        release_id=release_id,
        acquisition=acquisition,
        checksums=checksums,
        provider_outcome=provider_outcome,
        observation_start=observation_start,
        observation_end=observation_end,
        observation_time_column=observation_time_column,
        availability=availability,
        integrity=integrity,
        canonical_observation_path=canonical_observation_path,
        canonical_observation_count=canonical_observation_count,
        canonical_chain_path=canonical_chain_path,
        canonical_chain_count=canonical_chain_count,
        canonical_schema_version=canonical_schema_version,
        canonical_lineage_path=canonical_lineage_path,
        previous_release_id=previous_release_id,
        canonical_observation_delta_count=canonical_observation_delta_count,
        canonical_chain_delta_count=canonical_chain_delta_count,
        canonical_observation_merkle_root=canonical_observation_merkle_root,
        canonical_chain_merkle_root=canonical_chain_merkle_root,
        measurement_spec_path=measurement_spec_path,
        measurement_spec_version=measurement_spec_version,
        notes=notes,
    ))


def _canonical_official_observations(
    panel: pd.DataFrame,
    *,
    release_id: str,
    vintage_date: str,
    source_snapshot_sha256: str,
    provider_outcome: dict[str, Any] | None,
    canonical_prefix: str = "OFFICIAL",
    producer: str = "harvester.official",
) -> list[dict[str, Any]]:
    """Build canonical observations for the long official panel."""
    try:
        from harvester.core.availability import build_availability
        from system_runtime.canonical_ids import build_observation
    except ImportError:
        return []

    outcome = provider_outcome if isinstance(provider_outcome, dict) else {}
    failed_series = {str(item) for item in outcome.get("failed_series", [])}
    reused_status = {
        "reused_after_provider_failure",
        "provider_failed_no_acceptable_fallback",
        "environmentally_blocked",
    }
    series_attempts = outcome.get("series_attempts")
    if not isinstance(series_attempts, dict):
        series_attempts = {}
    availability_meta = outcome.get("availability")
    if not isinstance(availability_meta, dict):
        availability_meta = {
            "state": "UNKNOWN",
            "calendar_status": "UNCONFIGURED",
            "available_at": None,
            "retrieved_at": outcome.get("retrieved_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "decision_usable": False,
            "reason": "publication_calendar_or_available_at_not_evidenced",
        }
    required = {"date", "value"}
    if panel.empty or not required.issubset(panel.columns):
        return []

    records: list[dict[str, Any]] = []
    ordered = panel.sort_values(
        [column for column in ("series_id", "source_series_id", "date") if column in panel.columns]
    )
    for row in ordered.to_dict(orient="records"):
        observed = pd.to_datetime(row.get("date"), errors="coerce")
        if pd.isna(observed):
            continue
        raw_value = row.get("value")
        value: float | None
        if raw_value is None or pd.isna(raw_value):
            value = None
        else:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = None
        series_id = str(row.get("series_id") or row.get("source_series_id") or "").strip()
        source_series_id = str(row.get("source_series_id") or series_id).strip()
        if not series_id:
            continue
        quality_flag = row.get("quality_flag")
        quality_text = str(quality_flag or "").lower()
        if value is None:
            status = "MISSING"
        elif source_series_id in failed_series or outcome.get("status") in reused_status:
            status = "STALE"
        elif quality_text in {"2", "error", "missing", "source_down"} or quality_flag == 2:
            status = "STALE"
        else:
            status = str(availability_meta.get("state") or "UNKNOWN").upper()
            if status not in {
                "AVAILABLE", "STALE", "DELAYED", "MISSING", "NOT_APPLICABLE",
                "SOURCE_DOWN", "SCHEMA_CHANGED", "DISCONTINUED", "UNKNOWN",
            }:
                status = "UNKNOWN"
        attempts = series_attempts.get(source_series_id, [])
        selected_attempt = None
        if isinstance(attempts, list):
            selected_attempt = next(
                (item for item in reversed(attempts) if isinstance(item, dict) and item.get("outcome") == "success"),
                next((item for item in reversed(attempts) if isinstance(item, dict)), None),
            )
        provenance: dict[str, Any] = {
            "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "producer": producer,
            "run_id": release_id,
            "method": "registry_provider_observation",
            "quality_flag": quality_flag,
            "derivation": "MODELED" if str(row.get("source_id") or "").lower() == "derived" else "OBSERVED",
        }
        if isinstance(selected_attempt, dict):
            if selected_attempt.get("provider_attempt_id"):
                provenance["provider_attempt_id"] = selected_attempt["provider_attempt_id"]
            if selected_attempt.get("source_tier") is not None:
                provenance["source_tier"] = selected_attempt["source_tier"]
            if selected_attempt.get("failure_class"):
                provenance["failure_class"] = selected_attempt["failure_class"]
        source_signatures = outcome.get("series_source_signatures")
        source_signature = (
            source_signatures.get(source_series_id)
            if isinstance(source_signatures, dict)
            else None
        )
        if isinstance(source_signature, dict):
            provenance["source_signature"] = source_signature
        route_policy = outcome.get("route_policy")
        if isinstance(route_policy, dict):
            provenance["route_policy"] = route_policy
        availability = build_availability(
            state=status,
            observation_date=observed.date().isoformat(),
            source_vintage_at=str(row.get("vintage_date") or vintage_date),
            retrieved_at=str(availability_meta.get("retrieved_at") or outcome.get("retrieved_at")),
            published_at=availability_meta.get("published_at"),
            available_at=availability_meta.get("available_at"),
            calendar_status=str(availability_meta.get("calendar_status") or "UNCONFIGURED"),
            release_timezone=availability_meta.get("release_timezone"),
            release_cutoff_local=availability_meta.get("release_cutoff_local"),
            decision_usable=bool(availability_meta.get("decision_usable", False)),
            reason=str(availability_meta.get("reason") or ""),
        )
        records.append(
            build_observation(
                canonical_series_id=f"{canonical_prefix}:{series_id}",
                observed_at=observed.date().isoformat(),
                vintage_at=str(row.get("vintage_date") or vintage_date),
                value=value,
                source_id=str(row.get("source_id") or outcome.get("provider") or "harvester.registry"),
                unit=str(row.get("unit") or "") or None,
                status=status,
                scope={
                    "series_id": series_id,
                    "source_series_id": source_series_id,
                    "release_id": release_id,
                },
                source_snapshot_sha256=source_snapshot_sha256,
                availability=availability,
                provenance=provenance,
            )
        )
    return records


def stage_release(
    panel: pd.DataFrame,
    *,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    exports_root: str = "",
    notes: str = "",
) -> dict[str, Any]:
    validate_release_id(release_id)
    ex_root = (Path(exports_root) if exports_root else data_root() / "exports").expanduser().resolve()
    release_dir = resolve_release_dir(ex_root, release_id)

    for sub in ("data", "manifests", "provenance"):
        (release_dir / sub).mkdir(parents=True, exist_ok=True)

    data_path = release_dir / "data" / "official_panel.parquet"
    panel.to_parquet(data_path, index=False)
    panel_coverage = observation_coverage_from_frame(panel, time_column="date")
    provider_outcome = panel.attrs.get("provider_outcome")
    if not isinstance(provider_outcome, dict):
        provider_outcome = None
    panel_sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
    canonical_observations = _canonical_official_observations(
        panel,
        release_id=release_id,
        vintage_date=vintage_date,
        source_snapshot_sha256=panel_sha,
        provider_outcome=provider_outcome,
    )
    from harvester.core.canonical_chain import build_recorded_observation_chains
    from harvester.core.canonical_lineage import write_canonical_lineage

    official_lineage = write_canonical_lineage(
        release_dir=release_dir,
        dataset_id="official_panel",
        release_id=release_id,
        observations=canonical_observations,
        chain_builder=lambda delta: build_recorded_observation_chains(
            delta,
            release_id=release_id,
            producer="harvester.official",
            measurement_definition="Official panel value recorded for the release",
            policy_version="harvester.official.v1",
            predicate="official_value_recorded_on",
            label_factory=lambda observation: str(
                observation.get("canonical_series_id") or "official series"
            ),
        ),
        exports_root=ex_root,
        measurement_definition="Official panel value recorded for the release",
        predicate="official_value_recorded_on",
    )
    canonical_observation_relpath = official_lineage.observation_relpath
    canonical_chain_relpath = official_lineage.chain_relpath

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
        provider_outcome=provider_outcome,
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
        provider_outcome=provider_outcome,
        observation_start=(panel_coverage or {}).get("start"),
        observation_end=(panel_coverage or {}).get("end"),
        availability=(provider_outcome or {}).get("availability"),
        canonical_observation_path=canonical_observation_relpath,
        canonical_observation_count=official_lineage.provenance_fields["canonical_observation_count"],
        canonical_chain_path=canonical_chain_relpath,
        canonical_chain_count=official_lineage.provenance_fields["canonical_chain_count"],
        canonical_schema_version=official_lineage.provenance_fields["canonical_schema_version"],
        canonical_lineage_path=official_lineage.provenance_fields["canonical_lineage_path"],
        previous_release_id=official_lineage.provenance_fields.get("previous_release_id"),
        canonical_observation_delta_count=official_lineage.provenance_fields["canonical_observation_delta_count"],
        canonical_chain_delta_count=official_lineage.provenance_fields["canonical_chain_delta_count"],
        canonical_observation_merkle_root=official_lineage.provenance_fields["canonical_observation_merkle_root"],
        canonical_chain_merkle_root=official_lineage.provenance_fields["canonical_chain_merkle_root"],
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
        "canonical_observation_count": official_lineage.provenance_fields["canonical_observation_count"],
        "canonical_chain_count": official_lineage.provenance_fields["canonical_chain_count"],
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
        dates = pd.to_datetime(df["date"])
        return str(dates.min().strftime("%Y-%m-%d"))
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
    from harvester.registry import load_registry

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

    # Per-series provider attempts (ordered); fall back when preferred provider fails.
    requested_specs = [
        s
        for s in registry.active_series()
        if not s.is_derived and not _is_external_managed_series(s)
    ]
    requested_series = [s.source_series_id or s.canonical_id for s in requested_specs]
    all_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    succeeded_series: list[str] = []
    failed_series: list[str] = []
    provider_cache: dict[str, Any] = {}
    providers_used: set[str] = set()
    series_providers: dict[str, str] = {}
    series_source_signatures: dict[str, Any] = {}
    series_attempts: dict[str, Any] = {}
    fallback_used = False
    acquisition_sources: list[dict[str, Any]] = []

    def _provider(name: str):
        if name in provider_cache:
            return provider_cache[name]
        provider_kwargs: dict[str, Any] = {
            "api_key": keys.get(name, ""),
            "data_root": str(dr) if dr else "",
            "cache": cache,
        }
        if name == "etf_provider_chain":
            provider_kwargs["api_keys"] = {
                "tiingo": keys.get("tiingo", ""),
                "massive": keys.get("massive", ""),
            }
        if name.startswith("openbb"):
            provider_kwargs["settings_env"] = keys.get("openbb_settings_env", "")
        prov = build_provider(name, **provider_kwargs)
        provider_cache[name] = prov
        return prov

    def _normalize_result(r: Any, prov: Any) -> pd.DataFrame | None:
        if r.frame is None or r.frame.empty:
            return None
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
            c
            for c in [
                "date",
                "series_id",
                "source_id",
                "source_series_id",
                "value",
                # ETF provider results also carry raw OHLCV. Preserve those
                # optional columns so the cross-asset adapter can reuse the
                # actual bar instead of fabricating OHLCV from close.
                "open",
                "high",
                "low",
                "volume",
                "unit",
                "frequency",
                "vintage_date",
                "quality_flag",
            ]
            if c in df.columns
        ]
        return df[needed]

    for s in requested_specs:
        source_id = s.source_series_id or s.canonical_id
        got = False
        route_attempts: list[dict[str, Any]] = []
        series_started_at = utc_now()
        series_t0 = time.perf_counter()
        for provider_name in order_provider_priority(s.provider_priority):
            if provider_name not in enabled:
                continue
            try:
                prov = _provider(provider_name)
            except ProviderError as exc:
                route_attempts.append(
                    {
                        "provider": provider_name,
                        "source_id": provider_name,
                        "outcome": "failed",
                        "reason": "provider_init_error",
                        "error": str(exc)[:300],
                    }
                )
                errors.append({"provider": provider_name, "series_id": source_id, "error": str(exc)})
                continue
            results = prov.fetch_series([source_id])
            result = results[0] if results else None
            if result is None:
                route_attempts.append(
                    {
                        "provider": provider_name,
                        "source_id": str(getattr(prov, "source_id", provider_name)),
                        "outcome": "failed",
                        "reason": "empty_provider_result",
                        "error": "",
                    }
                )
                errors.append({
                    "provider": provider_name,
                    "series_id": source_id,
                    "error": "empty_provider_result",
                })
                continue
            provider_identity = str(result.provider or getattr(prov, "source_id", provider_name))
            route_attempt: dict[str, Any] = {
                "provider": provider_name,
                "source_id": provider_identity,
                "outcome": "failed",
                "reason": str(result.fetch_fallback_reason or "provider_error"),
                "error": str(result.fetch_error or "")[:300],
            }
            source_params = result.source_params if isinstance(result.source_params, dict) else {}
            source_engine = source_params.get("source_engine")
            if source_engine:
                route_attempt["source_engine"] = str(source_engine)
            if result.source_url:
                route_attempt["source_url"] = str(result.source_url)
            normalized = _normalize_result(result, prov)
            if normalized is not None:
                route_attempt["outcome"] = "success"
                # ``series_attempts`` is embedded in the release manifest;
                # successful attempts still need a non-empty reason under the
                # frozen provider-outcome contract.
                route_attempt["reason"] = "success"
                provider_attempts = source_params.get("provider_attempts")
                if isinstance(provider_attempts, list) and provider_attempts:
                    route_attempts.extend(provider_attempts)
                else:
                    route_attempts.append(route_attempt)
                all_results.append(normalized)
                succeeded_series.append(source_id)
                selected_provider = provider_identity
                providers_used.add(selected_provider)
                series_providers[source_id] = selected_provider
                source_signature = source_params.get("source_signature")
                if isinstance(source_signature, dict):
                    series_source_signatures[source_id] = dict(source_signature)
                series_attempts[source_id] = route_attempts
                fallback_used = fallback_used or len(route_attempts) > 1
                got = True
                break
            provider_attempts = source_params.get("provider_attempts")
            if isinstance(provider_attempts, list) and provider_attempts:
                route_attempts.extend(provider_attempts)
            else:
                route_attempts.append(route_attempt)
            fallback_used = fallback_used or len(route_attempts) > 1
            errors.append({
                "provider": provider_name,
                "series_id": source_id,
                "error": result.fetch_error or "unknown",
                "fallback_reason": result.fetch_fallback_reason,
            })
        if not got:
            if route_attempts:
                series_attempts[source_id] = route_attempts
            failed_series.append(source_id)
            logger.debug("no provider succeeded for %s", source_id)
        acquisition_sources.append(
            source_record(
                source_id=source_id,
                series_id=str(s.canonical_id),
                provider=str(series_providers.get(source_id) or ""),
                started_at=series_started_at,
                t0=series_t0,
                attempts=len(route_attempts),
                outcome="success" if got else "failed",
            )
        )

    if not requested_series:
        outcome = _provider_outcome(
            status="no_release_expected",
            provider="harvester.registry",
            requested_count=0,
            succeeded_count=0,
        )
    elif not all_results:
        error_text = "; ".join(
            f"{item.get('provider', 'unknown')}/{item.get('series_id', '')}: "
            f"{item.get('error', 'unknown')}"
            for item in errors
        )
        outcome = _provider_outcome(
            status="provider_failed_no_acceptable_fallback",
            provider="harvester.registry",
            requested_count=len(requested_series),
            succeeded_count=0,
            failed_series=failed_series or requested_series,
            fallback_reason="all_requested_series_failed",
            error=error_text or "no provider returned usable rows",
            providers_used=sorted(providers_used),
            series_providers=series_providers,
            series_attempts=series_attempts,
            series_source_signatures=series_source_signatures,
            fallback_used=fallback_used,
        )
    else:
        outcome = _provider_outcome(
            status=("partial_provider_success" if failed_series else "refreshed"),
            provider="harvester.registry",
            requested_count=len(requested_series),
            succeeded_count=len(set(succeeded_series)),
            failed_series=failed_series,
            fallback_reason="some_requested_series_failed" if failed_series else "",
            error=(
                "; ".join(
                    f"{item.get('provider', 'unknown')}/{item.get('series_id', '')}: "
                    f"{item.get('error', 'unknown')}"
                    for item in errors
                )
                if errors
                else ""
            ),
            providers_used=sorted(providers_used),
            series_providers=series_providers,
            series_attempts=series_attempts,
            series_source_signatures=series_source_signatures,
            fallback_used=fallback_used,
        )

    if not all_results:
        logger.warning("fetch_official_series_from_registry: no data returned")
        empty = pd.DataFrame(columns=[
            "date", "series_id", "source_id", "source_series_id",
            "value", "unit", "frequency", "vintage_date", "quality_flag",
        ])
        empty.attrs["provider_outcome"] = outcome
        empty.attrs["acquisition_sources"] = acquisition_sources
        return empty

    panel = pd.concat(all_results, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["series_id", "date"]).reset_index(drop=True)
    panel.attrs["provider_outcome"] = outcome
    panel.attrs["acquisition_sources"] = acquisition_sources
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
    from harvester.core.proxy_measurement import PROXY_SERIES_IDS

    proxy_ids = PROXY_SERIES_IDS
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


def _release_panel_candidates(exports_root: Path, *, exclude_release_id: str = "") -> list[Path]:
    """Ordered candidate benchmark panels (newest first), optionally skipping one release."""
    seen: set[Path] = set()
    ordered: list[Path] = []
    latest = exports_root / "latest"
    if latest.exists():
        try:
            resolved = latest.resolve()
            if not exclude_release_id or resolved.name != exclude_release_id:
                ordered.append(resolved / "data" / "benchmark_panel.parquet")
        except OSError:
            logger.warning("Unable to resolve latest Harvester release pointer: %s", latest, exc_info=True)
    for path in sorted(exports_root.glob("*/data/benchmark_panel.parquet"), reverse=True):
        if exclude_release_id and path.parent.parent.name == exclude_release_id:
            continue
        if path not in seen:
            ordered.append(path)
            seen.add(path)
    return ordered


def _carry_forward_missing_series(
    panel: pd.DataFrame,
    *,
    exports_root: Path,
    exclude_release_id: str = "",
) -> pd.DataFrame:
    """Fill gaps from a prior release when a preferred provider fails.

    Prevents OpenBB-first routing (or transient provider errors) from dropping
    previously admitted series such as FRED:RRPONTSYD from a new release.
    """
    from harvester.registry import load_registry

    provider_outcome = panel.attrs.get("provider_outcome")
    if isinstance(provider_outcome, dict):
        provider_outcome = dict(provider_outcome)

    registry = load_registry()
    required_specs = registry.required_series() if hasattr(registry, "required_series") else []
    required_for_release = {
        series.source_series_id or series.canonical_id
        for series in required_specs
    }
    expected: set[str] = set()
    for series in registry.active_series():
        if series.is_derived:
            continue
        cid = series.canonical_id
        expected.add(cid)
        expected.add(f"FRED:{cid}")
        expected.add(f"fred:{cid}")
    present = panel_identity_set(panel)
    missing = {item for item in expected if item not in present}
    if not missing:
        return panel
    bare = {m.split(":", 1)[1] if ":" in m else m for m in missing}
    carried = pd.DataFrame()
    for path in _release_panel_candidates(exports_root, exclude_release_id=exclude_release_id):
        if not path.exists():
            continue
        try:
            previous = pd.read_parquet(path)
        except Exception as exc:
            logger.warning(
                "Unable to read prior release panel %s: %s",
                path,
                type(exc).__name__,
            )
            continue
        if previous.empty or "series_id" not in previous.columns:
            continue
        prev_ids = previous["series_id"].astype(str)
        mask = prev_ids.isin(missing) | prev_ids.map(
            lambda value: value.split(":", 1)[1] if ":" in value else value
        ).isin(bare)
        candidate = previous.loc[mask].copy()
        if candidate.empty:
            continue
        carried = candidate
        break
    if carried.empty:
        return panel
    if not panel.empty and "series_id" in panel.columns:
        have = set(panel["series_id"].astype(str))
        carried = carried[~carried["series_id"].astype(str).isin(have)]
    if carried.empty:
        return panel
    logger.warning(
        "carry-forward %d rows / %d series from previous release",
        len(carried),
        carried["series_id"].nunique(),
    )
    if isinstance(provider_outcome, dict):
        carried_ids = set()
        if "source_series_id" in carried.columns:
            carried_ids.update(carried["source_series_id"].dropna().astype(str))
        elif "series_id" in carried.columns:
            carried_ids.update(
                carried["series_id"].dropna().astype(str).map(
                    lambda value: value.split(":", 1)[1] if ":" in value else value
                )
            )
        provider_failed_ids = set(provider_outcome.get("failed_series", []))
        failed_ids = set(provider_failed_ids)
        failed_ids.update(carried_ids)
        provider_outcome["failed_series"] = sorted(failed_ids)
        provider_outcome["failed_count"] = len(failed_ids)
        # A provider failure for a required-for-release series cannot become
        # an authoritative release.  Classify from the provider's failed
        # identifiers first: a carried row can satisfy a required alias (for
        # example CBOE:MOVE/VXTLT) even when the failed request itself was an
        # optional series.  Treating every carried row whose source id happens
        # to be required would therefore turn an optional outage into a
        # whole-run failure.  Optional series remain degraded evidence; the
        # downstream admission policy stays CONDITIONAL and still blocks
        # decision/current publication.
        required_failed = provider_failed_ids & required_for_release
        if required_failed:
            provider_outcome["status"] = "reused_after_provider_failure"
            provider_outcome["fallback_reason"] = (
                "carried_forward_required_series_after_provider_failure"
            )
        else:
            provider_outcome["status"] = "partial_provider_success"
            provider_outcome["fallback_reason"] = (
                "carried_forward_optional_series_after_provider_failure"
            )
    if panel.empty:
        result = carried.reset_index(drop=True)
    else:
        result = pd.concat([panel, carried], ignore_index=True)
    if isinstance(provider_outcome, dict):
        result.attrs["provider_outcome"] = provider_outcome
    return result


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
    data_contract_mode: str | None = None,
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
        build_derived_panel,
    )
    from harvester.quality import build_quality_report, write_quality_report
    from harvester.registry import load_registry

    registry = load_registry()
    if not vintage_date:
        vintage_date = datetime.now(UTC).strftime("%Y-%m-%d")
    if not as_of_date:
        as_of_date = vintage_date
    validate_release_id(release_id)
    ex_root = (Path(exports_root) if exports_root else data_root() / "exports").expanduser().resolve()
    release_dir = resolve_release_dir(ex_root, release_id)

    for sub in ("data", "manifests", "provenance", "quality_reports"):
        (release_dir / sub).mkdir(parents=True, exist_ok=True)

    local_steps: list[dict[str, Any]] = []
    stage_started_at = utc_now()

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
    acquisition_sources = list(panel.attrs.get("acquisition_sources") or [])
    panel = _carry_forward_missing_series(
        panel,
        exports_root=ex_root,
        exclude_release_id=release_id,
    )
    provider_outcome = panel.attrs.get("provider_outcome")
    if not isinstance(provider_outcome, dict):
        provider_outcome = None

    external_managed_series = {
        str(s.source_series_id or s.canonical_id)
        for s in registry.active_series()
        if not s.is_derived and _is_external_managed_series(s)
    }
    from harvester.providers.external_indicators import KNOWN_INDICATORS

    manual_external_series = {
        indicator.series_id
        for indicator in KNOWN_INDICATORS
        if indicator.acquisition_mode == "manual"
    }
    automated_external_series = external_managed_series - manual_external_series
    external_succeeded_series: dict[str, str] = {}
    external_failed_series: dict[str, str] = {
        series_id: "not_loaded"
        for series_id in automated_external_series
    }
    manual_series_status: dict[str, str] = {
        series_id: "manual_refresh_required"
        for series_id in sorted(external_managed_series & manual_external_series)
    }

    # ------------------------------------------------------------------
    # 2. Build derived series
    # ------------------------------------------------------------------
    derived_series = registry.derived_series()
    with track_local_step(local_steps, "derived_panel"):
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
                ManualDownloadRequired,
                external_series_to_long_panel,
                fetch_external_indicator,
                read_cached_external_indicator,
            )
            ext_results: dict[str, pd.Series] = {}
            for indicator in KNOWN_INDICATORS:
                cache_dir = harvester_raw_root() / "external_indicators"
                cache_dir.mkdir(parents=True, exist_ok=True)
                indicator_started_at = utc_now()
                indicator_t0 = time.perf_counter()
                indicator_outcome = "failed"
                indicator_provider = ""
                try:
                    if indicator.acquisition_mode == "manual":
                        result = read_cached_external_indicator(indicator, cache_dir=cache_dir)
                        if result is not None and not result.empty:
                            ext_results[indicator.series_id] = result
                            if indicator.series_id in manual_series_status:
                                manual_series_status[indicator.series_id] = "cached"
                            indicator_outcome = "success"
                            indicator_provider = str(indicator.authority_id)
                        else:
                            indicator_outcome = "manual"
                        continue
                    try:
                        result = fetch_external_indicator(
                            indicator,
                            cache_dir=cache_dir,
                            refresh=not cache,
                            timeout_sec=_external_indicator_timeout_seconds(),
                        )
                    except ManualDownloadRequired as exc:
                        logger.warning("external indicator unavailable: %s", exc)
                        if indicator.series_id in automated_external_series:
                            external_failed_series[indicator.series_id] = type(exc).__name__
                        continue
                    if result is not None and not result.empty:
                        ext_results[indicator.series_id] = result
                        if indicator.series_id in automated_external_series:
                            external_succeeded_series[indicator.series_id] = indicator.authority_id
                            external_failed_series.pop(indicator.series_id, None)
                        indicator_outcome = "success"
                        indicator_provider = str(indicator.authority_id)
                finally:
                    acquisition_sources.append(
                        source_record(
                            source_id=indicator.series_id,
                            series_id=indicator.series_id,
                            provider=indicator_provider,
                            started_at=indicator_started_at,
                            t0=indicator_t0,
                            attempts=1,
                            outcome=indicator_outcome,
                        )
                    )
            if ext_results:
                ext_panel = external_series_to_long_panel(ext_results, vintage_date=vintage_date)
        except Exception:
            logger.warning("external indicator fetch failed", exc_info=True)

    if include_external:
        provider_outcome = _merge_external_provider_outcome(
            provider_outcome,
            requested_series=automated_external_series,
            succeeded_series=external_succeeded_series,
            failed_series=external_failed_series,
            manual_series=manual_series_status,
        )

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
    from harvester.core.canonical_chain import build_recorded_observation_chains
    from harvester.core.canonical_lineage import write_canonical_lineage

    with track_local_step(local_steps, "jsonl_observations"):
        benchmark_observations = _canonical_official_observations(
            benchmark,
            release_id=release_id,
            vintage_date=vintage_date,
            source_snapshot_sha256=bench_sha,
            provider_outcome=provider_outcome,
            canonical_prefix="BENCHMARK",
            producer="harvester.complete",
        )

    with track_local_step(local_steps, "jsonl_chains"):
        benchmark_lineage = write_canonical_lineage(
            release_dir=release_dir,
            dataset_id="benchmark_panel",
            release_id=release_id,
            observations=benchmark_observations,
            chain_builder=lambda delta: build_recorded_observation_chains(
                delta,
                release_id=release_id,
                producer="harvester.complete",
                measurement_definition="Benchmark panel value recorded for the release",
                policy_version="harvester.benchmark_panel.v1",
                predicate="benchmark_value_recorded_on",
                label_factory=lambda observation: str(
                    observation.get("canonical_series_id") or "benchmark series"
                ),
            ),
            exports_root=ex_root,
            measurement_definition="Benchmark panel value recorded for the release",
            predicate="benchmark_value_recorded_on",
        )
    benchmark_observation_relpath = benchmark_lineage.observation_relpath
    benchmark_chain_relpath = benchmark_lineage.chain_relpath

    panel_dates = pd.to_datetime(benchmark["date"])
    benchmark_coverage = observation_coverage_from_frame(benchmark, time_column="date")
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
        provider_outcome=provider_outcome,
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
        provider_outcome=provider_outcome,
        observation_start=(benchmark_coverage or {}).get("start"),
        observation_end=(benchmark_coverage or {}).get("end"),
        canonical_observation_path=benchmark_observation_relpath,
        canonical_observation_count=benchmark_lineage.provenance_fields["canonical_observation_count"],
        canonical_chain_path=benchmark_chain_relpath,
        canonical_chain_count=benchmark_lineage.provenance_fields["canonical_chain_count"],
        canonical_schema_version=benchmark_lineage.provenance_fields["canonical_schema_version"],
        canonical_lineage_path=benchmark_lineage.provenance_fields["canonical_lineage_path"],
        previous_release_id=benchmark_lineage.provenance_fields.get("previous_release_id"),
        canonical_observation_delta_count=benchmark_lineage.provenance_fields["canonical_observation_delta_count"],
        canonical_chain_delta_count=benchmark_lineage.provenance_fields["canonical_chain_delta_count"],
        canonical_observation_merkle_root=benchmark_lineage.provenance_fields["canonical_observation_merkle_root"],
        canonical_chain_merkle_root=benchmark_lineage.provenance_fields["canonical_chain_merkle_root"],
        notes=notes or "Aggregated from registry-defined providers + derived computations.",
        acquisition_sources=acquisition_sources,
        local_steps=local_steps,
        started_at=stage_started_at,
        completed_at=utc_now(),
    )
    (release_dir / "provenance" / "benchmark_panel.provenance.json").write_text(
        json.dumps(bench_prov, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_quality_report(
        build_quality_report(
            "benchmark_panel",
            benchmark,
            as_of_date=as_of_date,
            required_columns=["date", "series_id", "source_id", "source_series_id", "value"],
            provider_outcome=provider_outcome,
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
    proxy_coverage = observation_coverage_from_frame(proxy_candidates, time_column="date")

    # Keep proxy candidates explicit and non-authoritative.  The measurement
    # specification records the source ladder, missingness semantics, and
    # promotion ceiling without emitting a canonical Observation->Claim chain.
    from harvester.core.proxy_measurement import (
        SCHEMA_VERSION as PROXY_MEASUREMENT_SPEC_VERSION,
    )
    from harvester.core.proxy_measurement import (
        build_proxy_measurement_spec,
    )

    proxy_measurement_spec = build_proxy_measurement_spec(
        release_id=release_id,
        derived_series=derived_series,
        registry=registry,
        candidate_panel=proxy_candidates,
    )
    proxy_measurement_spec_relpath = "provenance/proxy_candidate_panel.measurement_spec.json"
    (release_dir / proxy_measurement_spec_relpath).write_text(
        json.dumps(proxy_measurement_spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

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
        observation_start=(proxy_coverage or {}).get("start"),
        observation_end=(proxy_coverage or {}).get("end"),
        measurement_spec_path=proxy_measurement_spec_relpath,
        measurement_spec_version=PROXY_MEASUREMENT_SPEC_VERSION,
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
    from harvester.cross_asset_panel import (
        prefetched_panel_from_registry,
        stage_cross_asset_panel,
    )

    with track_local_step(local_steps, "cross_asset_panel"):
        cross_asset_info = stage_cross_asset_panel(
            release_dir,
            release_id=release_id,
            as_of_date=as_of_date,
            vintage_date=vintage_date,
            # CLI is normally launched from packages/harvester; derive the shared
            # System workspace from the canonical data root so history is merged
            # from /System/Data rather than an accidental package-local /Data.
            workspace=workspace_root(),
            # HYG/LQD/TLT may already have been acquired by the registry phase.
            # Reuse those rows and request only the remaining cross-asset symbols.
            prefetched_panel=prefetched_panel_from_registry(panel, workspace=workspace_root()),
            data_contract_mode=data_contract_mode,
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
    with track_local_step(local_steps, "promotion_gate"):
        gate_result = run_promotion_gate(
        release_dir,
        registry,
        panel_series_ids=panel_ids,
        sha256_verified=True,
        empty_panels=["corpus_index"] if proxy_row_count == 0 else [],
        cross_asset_row_count=int(cross_asset_info.get("row_count", 0)),
        cross_asset_symbol_count=int(cross_asset_info.get("symbol_count", 0)),
        cross_asset_provider_status=(
            cross_asset_info.get("provider_outcome", {}).get("status")
            if isinstance(cross_asset_info.get("provider_outcome"), dict)
            else None
        ),
        benchmark_provider_status=(
            provider_outcome.get("status")
            if isinstance(provider_outcome, dict)
            else None
        ),
        provider_failure_classes={
            scope: categories
            for scope, categories in {
                "cross_asset": _failed_attempt_failure_classes(cross_asset_info.get("provider_outcome")),
                "benchmark": _failed_attempt_failure_classes(provider_outcome),
            }.items()
            if categories
        },
    )
    write_gate_report(gate_result, release_id, release_dir)
    replace_local_steps(
        release_dir / "provenance" / "benchmark_panel.provenance.json",
        local_steps,
    )

    return {
        "release_id": release_id,
        "release_dir": str(release_dir),
        "benchmark_path": str(bench_path),
        "proxy_path": str(proxy_path),
        "proxy_measurement_spec_path": str(release_dir / proxy_measurement_spec_relpath),
        "cross_asset_path": cross_asset_info.get("data_path"),
        "benchmark_rows": len(benchmark),
        "proxy_rows": proxy_row_count,
        "cross_asset_rows": cross_asset_info.get("row_count", 0),
        "cross_asset_provider_outcome": cross_asset_info.get("provider_outcome", {}),
        "derived_series": [s.canonical_id for s in derived_series],
        "gate_state": gate_result.state,
        "gate_passed": gate_result.passed,
        "gate_blockers": gate_result.blockers,
        "gate_warnings": gate_result.warnings,
    }
