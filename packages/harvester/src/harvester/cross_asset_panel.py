"""Cross-asset daily ETF panel — Harvester evidence release dataset.

Builds OHLCV + derived return/volatility columns via the owned ETF provider
chain (Tiingo -> Massive -> yfinance) and stages
cross_asset_daily_panel.parquet into release bundles with manifest,
provenance, and quality report.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from harvester.official import make_manifest, make_provenance
from harvester.quality import build_quality_report, write_quality_report

logger = logging.getLogger(__name__)

DATASET_ID = "cross_asset_daily_panel"
PANEL_COLUMNS = [
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "volatility_20d",
    "drawdown_60d",
]

PROVIDER_OUTCOME_STATUSES = {
    "refreshed",
    "reused_same_content",
    "reused_after_provider_failure",
    "partial_provider_success",
    "provider_failed_no_acceptable_fallback",
    "no_release_expected",
    "environmentally_blocked",
}


class PanelFetchError(RuntimeError):
    """Provider acquisition failed with a structured, auditable outcome."""

    def __init__(self, message: str, outcome: dict[str, Any]) -> None:
        super().__init__(message)
        self.outcome = outcome


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
    provider_chain: list[str] | tuple[str, ...] | None = None,
    fallback_used: bool = False,
) -> dict[str, Any]:
    if status not in PROVIDER_OUTCOME_STATUSES:
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
        outcome["providers_used"] = sorted(set(providers_used))
    if series_providers:
        outcome["series_providers"] = {
            str(key): str(value) for key, value in sorted(series_providers.items())
        }
    if series_attempts:
        outcome["series_attempts"] = {
            str(key): value for key, value in sorted(series_attempts.items())
        }
    if provider_chain:
        outcome["provider_chain"] = [str(item) for item in provider_chain]
    if fallback_used:
        outcome["fallback_used"] = True
    return outcome


def _return_panel(
    panel: pd.DataFrame,
    outcome: dict[str, Any],
    *,
    return_outcome: bool,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, Any]]:
    panel.attrs["provider_outcome"] = outcome
    return (panel, outcome) if return_outcome else panel


def workspace_root() -> Path:
    """Best-effort workspace root when Harvester runs from System/."""
    cwd = Path.cwd()
    if (cwd / "Data" / "panels").exists() or (cwd / "governance").exists():
        return cwd
    return cwd


def resolve_etf_universe(workspace: Path | None = None) -> list[str]:
    root = workspace or workspace_root()
    config_path = root / "Config" / "data" / "etf_universe.yaml"
    if config_path.is_file():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        symbols: list[str] = []
        for key in ("equity", "sector", "credit", "rates", "dollar_commodity", "thematic"):
            symbols.extend(data.get(key, []) or [])
        extras = data.get("extras", []) or []
        symbols.extend(extras)
        deduped = sorted({str(s).strip() for s in symbols if str(s).strip()})
        if deduped:
            return deduped
    from harvester.providers.etf_yfinance import DEFAULT_ETF_TICKERS

    return sorted(DEFAULT_ETF_TICKERS.keys())


def _drop_invalid_quotes(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove rows with non-positive close prices (bad provider rows)."""
    if frame.empty or "close" not in frame.columns:
        return frame
    return frame[frame["close"].astype(float) > 0].copy()


def load_existing_panel(workspace: Path | None = None) -> pd.DataFrame:
    root = workspace or workspace_root()
    path = root / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    if not path.is_file():
        return pd.DataFrame(columns=PANEL_COLUMNS)
    frame = pd.read_parquet(path)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"])
    return _drop_invalid_quotes(frame)


def load_latest_release_panel(
    workspace: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read the finalized Harvester panel without acquiring from a provider.

    The scheduled refresh step is a consumer/mirror operation.  It must not
    call yfinance after ``harvester daily-release`` has already performed the
    authoritative acquisition.  Missing legacy provider metadata is treated
    as a reused release so freshness/admission remains conservative.
    """
    root = workspace or workspace_root()
    release_root = root / "Data" / "harvester" / "exports" / "latest"
    data_path = release_root / "data" / f"{DATASET_ID}.parquet"
    manifest_path = release_root / "manifests" / f"{DATASET_ID}.manifest.json"
    if not data_path.is_file():
        return (
            pd.DataFrame(columns=PANEL_COLUMNS),
            _provider_outcome(
                status="provider_failed_no_acceptable_fallback",
                provider="harvester.release",
                requested_count=0,
                succeeded_count=0,
                fallback_reason="finalized_cross_asset_panel_missing",
            ),
        )

    frame = pd.read_parquet(data_path)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = _drop_invalid_quotes(frame)
    outcome: dict[str, Any] = {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        candidate = payload.get("provider_outcome")
        if isinstance(candidate, dict):
            outcome = dict(candidate)
    except (OSError, json.JSONDecodeError):
        outcome = {}
    if not outcome:
        outcome = _provider_outcome(
            status="reused_same_content",
            provider="harvester.release",
            requested_count=int(frame["symbol"].nunique()) if "symbol" in frame.columns else 0,
            succeeded_count=int(frame["symbol"].nunique()) if "symbol" in frame.columns else 0,
            fallback_reason="legacy_release_manifest_without_provider_outcome",
        )
    frame.attrs["provider_outcome"] = outcome
    return frame, outcome


def prefetched_panel_from_registry(
    panel: pd.DataFrame | None,
    *,
    workspace: Path | None = None,
) -> pd.DataFrame:
    """Adapt registry-acquired ETF rows for the cross-asset builder.

    ``stage_complete_release`` already acquires registry series such as HYG,
    LQD, and TLT before it builds the wider cross-asset panel. Reusing those
    rows keeps one release on one acquisition path; the builder only requests
    tickers that were not present in the registry result. The returned frame
    intentionally contains only raw OHLCV columns, so derived columns are
    still computed once by :func:`build_cross_asset_panel`.
    """
    empty = pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])
    if panel is None or panel.empty or "source_series_id" not in panel.columns:
        return empty

    universe = set(resolve_etf_universe(workspace))
    if not universe:
        return empty
    source_series = panel[panel["source_series_id"].astype(str).isin(universe)].copy()
    if source_series.empty or "date" not in source_series.columns:
        return empty

    source_series["date"] = pd.to_datetime(source_series["date"], errors="coerce")
    source_series["symbol"] = source_series["source_series_id"].astype(str)
    if "close" not in source_series.columns:
        if "value" not in source_series.columns:
            return empty
        source_series["close"] = source_series["value"]
    for column in ("open", "high", "low", "volume"):
        if column not in source_series.columns:
            source_series[column] = source_series["close"]
    result = source_series[
        ["date", "symbol", "open", "high", "low", "close", "volume"]
    ].copy()
    result = result[result["date"].notna()]
    result.attrs["provider_outcome"] = dict(panel.attrs.get("provider_outcome", {}))
    return result


def fetch_recent_ohlcv(symbols: list[str], *, period: str = "5d") -> pd.DataFrame:
    from harvester.providers.etf_market_data import EtfProviderChain

    requested_symbols = sorted(set(symbols))
    if not requested_symbols:
        return _return_panel(
            pd.DataFrame(columns=PANEL_COLUMNS),
            _provider_outcome(
                status="no_release_expected",
                provider="etf_provider_chain",
                requested_count=0,
                succeeded_count=0,
            ),
            return_outcome=False,
        )

    tickers = {symbol: symbol for symbol in requested_symbols}
    root = workspace_root()
    provider = EtfProviderChain(
        tickers=tickers,
        period=period,
        data_root=str(root / "Data" / "harvester"),
    )
    results = provider.fetch_series(requested_symbols)
    series_providers = {
        result.series_id: result.provider
        for result in results
        if result is not None and not result.empty()
    }
    providers_used = sorted(set(series_providers.values()))
    series_attempts = {
        result.series_id: result.source_params.get("provider_attempts", [])
        for result in results
        if result is not None and result.source_params.get("provider_attempts")
    }
    fallback_used = any(
        result is not None and result.source_params.get("fallback_from")
        for result in results
        if result is not None
    )

    rows: list[dict[str, Any]] = []
    for result in results:
        if result.frame is None or result.frame.empty:
            if result.fetch_error:
                logger.warning("ETF fetch failed for %s: %s", result.series_id, result.fetch_error)
            continue
        for _, row in result.frame.iterrows():
            # All chain providers normalize Close to "value"; accept either
            # name so provider-native fixtures remain compatible.
            close = row.get("close", row.get("value", 0))
            rows.append(
                {
                    "date": str(row.get("date", ""))[:10],
                    "symbol": result.series_id,
                    "close": float(close),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "volume": float(row.get("volume", 0)),
                }
            )
    if not rows:
        failed_series = requested_symbols
        outcome = _provider_outcome(
            status="provider_failed_no_acceptable_fallback",
            provider="etf_provider_chain",
            requested_count=len(requested_symbols),
            succeeded_count=0,
            failed_series=failed_series,
            fallback_reason="all_requested_symbols_failed",
            error="provider returned no usable rows",
            providers_used=providers_used,
            series_providers=series_providers,
            series_attempts=series_attempts,
            provider_chain=list(provider.provider_order),
            fallback_used=fallback_used,
        )
        raise PanelFetchError(
            f"ETF fetch produced no usable rows for {len(requested_symbols)} symbols "
            f"({len(failed_series)} failed/empty)",
            outcome,
        )
    if not rows:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = _drop_invalid_quotes(frame)
    succeeded_series = sorted(set(frame["symbol"].astype(str))) if not frame.empty else []
    failed_series = sorted(set(requested_symbols) - set(succeeded_series))
    status = "partial_provider_success" if failed_series else "refreshed"
    outcome = _provider_outcome(
        status=status,
        provider="etf_provider_chain",
        requested_count=len(requested_symbols),
        succeeded_count=len(succeeded_series),
        failed_series=failed_series,
        fallback_reason="partial_provider_failure" if failed_series else "",
        providers_used=providers_used,
        series_providers=series_providers,
        series_attempts=series_attempts,
        provider_chain=list(provider.provider_order),
        fallback_used=fallback_used,
    )
    if failed_series:
        logger.warning(
            "ETF fetch incomplete: %d/%d symbols failed or empty",
            len(failed_series),
            len(requested_symbols),
        )
    return _return_panel(frame, outcome, return_outcome=False)


def compute_derived_columns(frame: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for symbol, group in frame.groupby("symbol"):
        # The provider chain can return the same (symbol, date) more than
        # once (for example, rounded and unrounded Yahoo rows).  Keep the
        # last deterministic row before calculating returns; otherwise the
        # duplicate survives into the workspace mirror and downstream joins
        # produce a non-unique DatetimeIndex.
        group = group.sort_values("date").drop_duplicates("date", keep="last").copy()
        close = group["close"].astype(float)
        group["return_1d"] = close.pct_change(1)
        group["return_5d"] = close.pct_change(5)
        group["return_20d"] = close.pct_change(20)
        group["return_60d"] = close.pct_change(60)
        group["volatility_20d"] = close.pct_change(1).rolling(20, min_periods=10).std() * np.sqrt(252)
        rolling_max = close.rolling(60, min_periods=20).max()
        group["drawdown_60d"] = (close - rolling_max) / rolling_max
        parts.append(group)
    if not parts:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    merged = pd.concat(parts, ignore_index=True)
    for column in PANEL_COLUMNS:
        if column not in merged.columns:
            merged[column] = np.nan
    return merged[PANEL_COLUMNS].sort_values(["symbol", "date"]).reset_index(drop=True)


def build_cross_asset_panel(
    *,
    workspace: Path | None = None,
    fetch_period: str = "5d",
    prefetched_panel: pd.DataFrame | None = None,
    return_outcome: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, Any]]:
    """Merge history, same-release prefetched rows, and a bounded fresh fetch.

    ``prefetched_panel`` is populated by the preceding registry acquisition.
    It is deliberately consumed before calling :func:`fetch_recent_ohlcv` so
    the same release cannot request a ticker twice through two code paths.
    """
    root = workspace or workspace_root()
    existing = load_existing_panel(root)
    symbols = sorted(set(resolve_etf_universe(root)))
    if not symbols and not existing.empty:
        symbols = sorted(existing["symbol"].astype(str).unique())

    prefetched = prefetched_panel.copy() if prefetched_panel is not None else pd.DataFrame()
    if not prefetched.empty:
        required_prefetch_columns = {"date", "symbol", "close"}
        if not required_prefetch_columns.issubset(prefetched.columns):
            prefetched = pd.DataFrame()
        else:
            prefetched["date"] = pd.to_datetime(prefetched["date"], errors="coerce")
            prefetched = prefetched[prefetched["date"].notna()].copy()
            if symbols:
                prefetched = prefetched[prefetched["symbol"].astype(str).isin(symbols)]
            else:
                symbols = sorted(set(prefetched["symbol"].astype(str)))

    if not symbols:
        return _return_panel(
            pd.DataFrame(columns=PANEL_COLUMNS),
            _provider_outcome(
                status="no_release_expected",
                provider="etf_provider_chain",
                requested_count=0,
                succeeded_count=0,
            ),
            return_outcome=return_outcome,
        )

    prefetched_symbols = sorted(set(prefetched["symbol"].astype(str))) if not prefetched.empty else []
    remaining_symbols = [symbol for symbol in symbols if symbol not in set(prefetched_symbols)]
    provider_failure_reused = False
    prefetched_outcome = prefetched.attrs.get("provider_outcome")

    try:
        fresh = fetch_recent_ohlcv(remaining_symbols, period=fetch_period)
        outcome = fresh.attrs.get("provider_outcome")
        if not isinstance(outcome, dict):
            fresh_symbols = sorted(set(fresh["symbol"].astype(str))) if "symbol" in fresh.columns else []
            failed_series = sorted(set(remaining_symbols) - set(fresh_symbols))
            outcome = _provider_outcome(
                status=("reused_same_content" if fresh.empty else "partial_provider_success" if failed_series else "refreshed"),
                provider="etf_provider_chain",
                requested_count=len(remaining_symbols),
                succeeded_count=len(fresh_symbols),
                failed_series=failed_series,
                fallback_reason="partial_provider_failure" if failed_series else "",
            )
    except PanelFetchError as exc:
        outcome = dict(exc.outcome)
        # Yahoo often rate-limits the full universe mid-pipeline. Keep the
        # workspace mirror so harvester/refresh do not hard-fail the release.
        if existing.empty and prefetched.empty:
            raise
        provider_failure_reused = True
        outcome["status"] = "reused_after_provider_failure"
        outcome["fallback_reason"] = "retained_existing_panel_after_provider_failure"
        logger.warning(
            "ETF fetch failed entirely (%s); retaining existing panel (%d rows)",
            exc,
            len(existing),
        )
        fresh = pd.DataFrame(
            columns=["date", "symbol", "open", "high", "low", "close", "volume"]
        )
    except RuntimeError as exc:
        if existing.empty and prefetched.empty:
            raise
        provider_failure_reused = True
        outcome = _provider_outcome(
            status="reused_after_provider_failure",
            provider="etf_provider_chain",
            requested_count=len(remaining_symbols),
            succeeded_count=0,
            failed_series=remaining_symbols,
            fallback_reason="retained_existing_panel_after_provider_failure",
            error=str(exc),
        )
        logger.warning(
            "ETF fetch failed entirely (%s); retaining existing panel (%d rows)",
            exc,
            len(existing),
        )
        fresh = pd.DataFrame(
            columns=["date", "symbol", "open", "high", "low", "close", "volume"]
        )

    fresh_symbols = sorted(set(fresh["symbol"].astype(str))) if "symbol" in fresh.columns else []
    succeeded_symbols = sorted(set(prefetched_symbols) | set(fresh_symbols))
    failed_series = sorted(set(symbols) - set(succeeded_symbols))
    outcome["provider"] = "etf_provider_chain"
    outcome["requested_count"] = len(symbols)
    outcome["succeeded_count"] = len(succeeded_symbols)
    outcome["failed_count"] = len(failed_series)
    outcome["failed_series"] = failed_series
    if prefetched_symbols:
        outcome["prefetched_series"] = prefetched_symbols
        outcome["prefetch_owner"] = "harvester.registry_acquisition"
        if isinstance(prefetched_outcome, dict):
            for field in ("providers_used", "series_providers", "provider_chain"):
                inherited = prefetched_outcome.get(field)
                if inherited:
                    if field == "providers_used":
                        outcome[field] = sorted(
                            set(outcome.get(field, [])) | set(str(item) for item in inherited)
                        )
                    elif field == "series_providers":
                        outcome[field] = {
                            **dict(inherited),
                            **dict(outcome.get(field, {})),
                        }
                    elif field == "provider_chain" and not outcome.get(field):
                        outcome[field] = list(inherited)
            inherited_attempts = prefetched_outcome.get("series_attempts")
            if isinstance(inherited_attempts, dict):
                outcome["series_attempts"] = {
                    **inherited_attempts,
                    **dict(outcome.get("series_attempts", {})),
                }
            outcome["fallback_used"] = bool(
                outcome.get("fallback_used") or prefetched_outcome.get("fallback_used")
            )
    if provider_failure_reused:
        outcome["status"] = "reused_after_provider_failure"
    elif failed_series:
        outcome["status"] = (
            "partial_provider_success"
            if succeeded_symbols
            else "provider_failed_no_acceptable_fallback"
        )
    elif succeeded_symbols:
        outcome["status"] = "refreshed"

    acquired = (
        pd.concat([prefetched, fresh], ignore_index=True)
        if not prefetched.empty or not fresh.empty
        else pd.DataFrame()
    )
    if existing.empty and acquired.empty:
        outcome["status"] = "provider_failed_no_acceptable_fallback"
        return _return_panel(
            pd.DataFrame(columns=PANEL_COLUMNS), outcome, return_outcome=return_outcome
        )

    if existing.empty:
        merged = acquired
    elif acquired.empty:
        merged = existing.copy()
    else:
        # Replace only (symbol, date) pairs present in the newly acquired
        # rows. Date-only replacement deletes other symbols on partial
        # rate-limit failures.
        existing = existing.copy()
        existing["_key"] = list(
            zip(existing["symbol"].astype(str), pd.to_datetime(existing["date"]))
        )
        acquired_keys = set(
            zip(acquired["symbol"].astype(str), pd.to_datetime(acquired["date"]))
        )
        kept = existing[~existing["_key"].isin(acquired_keys)].drop(columns=["_key"])
        merged = pd.concat([kept, acquired], ignore_index=True)

    for column in PANEL_COLUMNS:
        if column not in merged.columns:
            merged[column] = np.nan
    merged = compute_derived_columns(merged)
    return _return_panel(merged, outcome, return_outcome=return_outcome)


def sync_panel_to_workspace(panel: pd.DataFrame, workspace: Path | None = None) -> Path:
    """Write only the writable workspace mirror.

    ``Data/harvester/exports/latest`` is the immutable, finalized Harvester
    release and is therefore a read-only input to this compatibility mirror.
    Keeping the write boundary here explicit prevents a refresh consumer from
    silently mutating canonical release bytes when a test or local checkout
    happens to leave that directory writable.
    """
    root = workspace or workspace_root()
    path = root / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(path, index=False)
    return path


def _canonical_observation_records(
    panel: pd.DataFrame,
    *,
    release_id: str,
    vintage_date: str,
    source_snapshot_sha256: str,
    provider_outcome: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build release-scoped canonical observations for ETF close values.

    This is intentionally an Observation-only artifact. Measurement, Evidence
    and Claim writers consume it in later migration stages; no new canonical
    ID family is introduced here.
    """
    try:
        from system_runtime.canonical_ids import build_observation
    except ImportError:
        logger.warning("system_runtime canonical IDs unavailable; skipping observation sidecar")
        return []

    series_providers = provider_outcome.get("series_providers")
    if not isinstance(series_providers, dict):
        series_providers = {}
    series_attempts = provider_outcome.get("series_attempts")
    if not isinstance(series_attempts, dict):
        series_attempts = {}
    failed_series = {
        str(item) for item in provider_outcome.get("failed_series", [])
    }
    reused_statuses = {
        "reused_same_content",
        "reused_after_provider_failure",
        "provider_failed_no_acceptable_fallback",
        "environmentally_blocked",
    }
    records: list[dict[str, Any]] = []
    if panel.empty or not {"date", "symbol", "close"}.issubset(panel.columns):
        return records

    for row in panel.sort_values(["symbol", "date"]).itertuples(index=False):
        symbol = str(getattr(row, "symbol", "")).strip()
        observed = pd.to_datetime(getattr(row, "date", None), errors="coerce")
        close = getattr(row, "close", None)
        if not symbol or pd.isna(observed) or close is None or pd.isna(close):
            continue
        try:
            value = float(close)
        except (TypeError, ValueError):
            continue

        attempts = series_attempts.get(symbol, [])
        selected_attempt = next(
            (
                item
                for item in reversed(attempts)
                if isinstance(item, dict) and item.get("outcome") == "success"
            ),
            next((item for item in reversed(attempts) if isinstance(item, dict)), None),
        ) if isinstance(attempts, list) else None
        provenance: dict[str, Any] = {
            "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "producer": "harvester.cross_asset_panel",
            "run_id": release_id,
            "method": "provider_chain_close_observation",
        }
        if isinstance(selected_attempt, dict):
            if selected_attempt.get("provider_attempt_id"):
                provenance["provider_attempt_id"] = selected_attempt["provider_attempt_id"]
            if selected_attempt.get("source_tier") is not None:
                provenance["source_tier"] = selected_attempt["source_tier"]
            if selected_attempt.get("failure_class"):
                provenance["failure_class"] = selected_attempt["failure_class"]
        status = "STALE" if symbol in failed_series or provider_outcome.get("status") in reused_statuses else "AVAILABLE"
        source_id = str(series_providers.get(symbol) or provider_outcome.get("provider") or "etf_provider_chain")
        records.append(
            build_observation(
                canonical_series_id=f"ETF:{symbol}:close",
                observed_at=observed.date().isoformat(),
                vintage_at=vintage_date,
                value=value,
                source_id=source_id,
                unit="USD",
                status=status,
                scope={"symbol": symbol, "release_id": release_id},
                source_snapshot_sha256=source_snapshot_sha256,
                provenance=provenance,
            )
        )
    return records


def _canonical_chain_records(
    observations: list[dict[str, Any]],
    *,
    release_id: str,
) -> list[dict[str, Any]]:
    """Build a bounded full chain for each recorded ETF close observation.

    The claim is intentionally a recording statement, not a market judgment.
    It is linked to real observation/measurement/evidence IDs but carries a
    diagnostic ceiling so downstream promotion cannot treat a close price as a
    research conclusion.
    """
    try:
        from system_runtime.canonical_ids import (
            build_chain,
            build_claim,
            build_evidence,
            build_measurement,
        )
    except ImportError:
        logger.warning("system_runtime canonical IDs unavailable; skipping chain sidecar")
        return []

    chains: list[dict[str, Any]] = []
    for observation in observations:
        scope = observation.get("scope") if isinstance(observation.get("scope"), dict) else {}
        symbol = str(scope.get("symbol") or observation.get("canonical_series_id", "")).strip()
        observed_at = str(observation.get("observed_at") or "").strip()
        status = str(observation.get("status") or "UNKNOWN")
        claim_status = {
            "AVAILABLE": "WATCH",
            "STALE": "STALE",
        }.get(status, "INSUFFICIENT_DATA")
        measurement = build_measurement(
            observation_ids=[observation["observation_id"]],
            measurement_definition="ETF close price recorded for the release",
            value=observation.get("value"),
            unit=observation.get("unit"),
            status=status,
            derivation="OBSERVED",
            method_version="harvester.cross_asset_panel.v1",
            provenance={
                "captured_at": observation["provenance"]["captured_at"],
                "producer": "harvester.cross_asset_panel",
                "run_id": release_id,
                "statement_kind": "recorded_observation",
            },
        )
        evidence = build_evidence(
            measurement_ids=[measurement["measurement_id"]],
            evidence_role="PRIMARY",
            source_id=str(observation["source"]["source_id"]),
            release_id=release_id,
            source_snapshot_sha256=observation["source"].get("snapshot_sha256"),
            status=status,
            provenance={
                "captured_at": observation["provenance"]["captured_at"],
                "producer": "harvester.cross_asset_panel",
                "run_id": release_id,
                "statement_kind": "recorded_observation",
            },
        )
        claim = build_claim(
            claim_text=f"{symbol} close was recorded on {observed_at}",
            subject=symbol,
            predicate="close_recorded_on",
            policy_version="harvester.cross_asset_panel.v1",
            evidence_ids=[evidence["evidence_id"]],
            status=claim_status,
            confidence=None,
            provenance={
                "captured_at": observation["provenance"]["captured_at"],
                "producer": "harvester.cross_asset_panel",
                "run_id": release_id,
                "statement_kind": "recorded_observation",
                "claim_ceiling": "diagnostic_observation_only",
                "promotion_allowed": False,
            },
        )
        chains.append(
            build_chain(
                observation=observation,
                measurement=measurement,
                evidence=evidence,
                claim=claim,
            )
        )
    return chains


def stage_cross_asset_panel(
    release_dir: Path,
    *,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    workspace: Path | None = None,
    fetch_period: str = "5d",
    prefetched_panel: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build and stage cross_asset_daily_panel into an in-progress release.

    ``prefetched_panel`` carries ETF rows already acquired by the registry
    phase of the same release; it prevents a second provider request.
    """
    panel, provider_outcome = build_cross_asset_panel(
        workspace=workspace,
        fetch_period=fetch_period,
        prefetched_panel=prefetched_panel,
        return_outcome=True,
    )
    data_dir = release_dir / "data"
    manifests_dir = release_dir / "manifests"
    provenance_dir = release_dir / "provenance"
    for directory in (data_dir, manifests_dir, provenance_dir, release_dir / "quality_reports"):
        directory.mkdir(parents=True, exist_ok=True)

    data_path = data_dir / f"{DATASET_ID}.parquet"
    if panel.empty:
        pd.DataFrame(columns=PANEL_COLUMNS).to_parquet(data_path, index=False)
    else:
        panel.to_parquet(data_path, index=False)

    sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
    size = data_path.stat().st_size
    row_count = len(panel)
    dates = pd.to_datetime(panel["date"], errors="coerce") if "date" in panel.columns else pd.Series(dtype="datetime64[ns]")
    observation_start = dates.min().strftime("%Y-%m-%d") if dates.notna().any() else ""
    observation_end = dates.max().strftime("%Y-%m-%d") if dates.notna().any() else ""

    canonical_observation_relpath = (
        f"provenance/{DATASET_ID}.canonical_observations.jsonl"
    )
    canonical_observation_path = release_dir / canonical_observation_relpath
    canonical_observations = _canonical_observation_records(
        panel,
        release_id=release_id,
        vintage_date=vintage_date,
        source_snapshot_sha256=sha,
        provider_outcome=provider_outcome,
    )
    canonical_observation_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in canonical_observations),
        encoding="utf-8",
    )
    canonical_chains = _canonical_chain_records(canonical_observations, release_id=release_id)
    canonical_chain_relpath = f"provenance/{DATASET_ID}.canonical_chains.jsonl"
    canonical_chain_path = release_dir / canonical_chain_relpath
    canonical_chain_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in canonical_chains),
        encoding="utf-8",
    )

    columns = [
        {"name": "date", "dtype": "date", "nullable": False, "description": "Trading date", "semantic_role": "time_index"},
        {"name": "symbol", "dtype": "string", "nullable": False, "description": "ETF ticker", "semantic_role": "category"},
        {"name": "close", "dtype": "float64", "nullable": True, "description": "Close price", "semantic_role": "measure"},
        {"name": "return_1d", "dtype": "float64", "nullable": True, "description": "1-day return", "semantic_role": "measure"},
        {"name": "volatility_20d", "dtype": "float64", "nullable": True, "description": "20-day realized vol", "semantic_role": "measure"},
    ]

    manifest = make_manifest(
        dataset_id=DATASET_ID,
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        data_path=data_path,
        provider="harvester.providers.etf_market_data",
        source_url="provider:etf_provider_chain",
        columns=columns,
        provenance_path=f"provenance/{DATASET_ID}.provenance.json",
        quality_report_path=f"quality_reports/{DATASET_ID}.quality.json",
        row_count=row_count,
        observation_start=observation_start,
        observation_end=observation_end,
        provider_outcome=provider_outcome,
        notes="Cross-asset ETF OHLCV panel for K/X confirmation and feedback loops.",
    )
    manifest["data_file"]["sha256"] = sha
    manifest["data_file"]["byte_size"] = size
    (manifests_dir / f"{DATASET_ID}.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    provenance = make_provenance(
        dataset_id=DATASET_ID,
        release_id=release_id,
        method="api_client",
        source_identifier="harvester.providers.etf_market_data",
        final_sha256=sha,
        provider_outcome=provider_outcome,
        observation_start=observation_start or None,
        observation_end=observation_end or None,
        canonical_observation_path=canonical_observation_relpath,
        canonical_observation_count=len(canonical_observations),
        canonical_chain_path=canonical_chain_relpath,
        canonical_chain_count=len(canonical_chains),
        canonical_schema_version="system.canonical_chain.v1",
        notes="Built from the owned ETF provider chain with workspace history merge.",
    )
    (provenance_dir / f"{DATASET_ID}.provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    write_quality_report(
        build_quality_report(
            DATASET_ID,
            panel,
            as_of_date=as_of_date,
            required_columns=["date", "symbol", "close"],
            allow_empty=False,
            provider_outcome=provider_outcome,
        ),
        release_dir,
        DATASET_ID,
    )

    workspace_path = sync_panel_to_workspace(panel, workspace)
    return {
        "dataset_id": DATASET_ID,
        "data_path": str(data_path),
        "workspace_path": str(workspace_path),
        "row_count": row_count,
        "symbol_count": int(panel["symbol"].nunique()) if not panel.empty else 0,
        "sha256": sha,
        "provider_outcome": provider_outcome,
        "canonical_observation_path": str(canonical_observation_path),
        "canonical_observation_count": len(canonical_observations),
        "canonical_chain_path": str(canonical_chain_path),
        "canonical_chain_count": len(canonical_chains),
        "observation_start": observation_start,
        "observation_end": observation_end,
    }
