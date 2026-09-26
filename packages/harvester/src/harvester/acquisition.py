"""Provider acquisition entrypoints owned by the Harvester boundary."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import logging
from pathlib import Path
import threading
import time
from typing import Any

import pandas as pd

from harvester.provider_catalog import (
    DEFAULT_OFFICIAL_PROVIDERS,
    OFFICIAL_SERIES_MAP,
)
from harvester.core.acquisition_timing import source_record, utc_now
from harvester.provider_routing import (
    _is_external_managed_series,
    _provider_outcome,
    order_provider_priority,
)
from harvester.providers import ProviderError, build_provider
from system_runtime.context import RuntimeContext

logger = logging.getLogger(__name__)


def fetch_official_series(
    *,
    as_of_date: str = "",
    data_root: str = "",
    providers: list[str] | None = None,
    cache: bool = True,
    api_keys: dict[str, str] | None = None,
    provider_factory: Callable[..., Any] | None = None,
    series_catalog: dict[str, dict[str, Any]] | None = None,
    default_providers: list[str] | None = None,
) -> pd.DataFrame:
    factory = provider_factory or build_provider
    catalog = OFFICIAL_SERIES_MAP if series_catalog is None else series_catalog
    defaults = DEFAULT_OFFICIAL_PROVIDERS if default_providers is None else default_providers
    dr = Path(data_root) if data_root else RuntimeContext.current_context().data_root
    keys = api_keys or {}
    enabled: list[str]
    if providers is None:
        enabled = list(defaults)
    else:
        enabled = list(providers)
    vintage = datetime.now(UTC).strftime("%Y-%m-%d")
    if not as_of_date:
        as_of_date = vintage

    all_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for provider_name in enabled:
        config = catalog.get(provider_name)
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
            prov = factory(
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

def fetch_official_series_from_registry(
    *,
    as_of_date: str = "",
    data_root: str = "",
    providers: list[str] | None = None,
    cache: bool = True,
    api_keys: dict[str, str] | None = None,
    deadline_monotonic: float | None = None,
    provider_factory: Callable[..., Any] | None = None,
    outcome_factory: Callable[..., dict[str, Any]] | None = None,
    route_orderer: Callable[[list[str] | tuple[str, ...]], list[str]] | None = None,
    external_classifier: Callable[[Any], bool] | None = None,
    default_providers: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch all active series from the YAML registry.

    Uses provider_priority to route each series through its primary provider.
    Returns a canonical benchmark_panel in long format.
    """
    from harvester.registry import load_registry

    factory = provider_factory or build_provider
    make_outcome = outcome_factory or _provider_outcome
    route = route_orderer or order_provider_priority
    is_external = external_classifier or _is_external_managed_series
    defaults = DEFAULT_OFFICIAL_PROVIDERS if default_providers is None else default_providers
    registry = load_registry()
    dr = Path(data_root) if data_root else RuntimeContext.current_context().data_root
    keys = api_keys or {}
    vintage = datetime.now(UTC).strftime("%Y-%m-%d")
    if not as_of_date:
        as_of_date = vintage

    # Determine which providers to use
    enabled: set[str]
    if providers is not None:
        enabled = set(providers)
    else:
        enabled = set(defaults)

    # Per-series provider attempts (ordered); fall back when preferred provider fails.
    requested_specs = [
        s
        for s in registry.active_series()
        if not s.is_derived and not is_external(s)
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
    deadline_skipped_series: list[str] = []
    result_lock = threading.Lock()

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
        prov = factory(name, **provider_kwargs)
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

    def _consume_spec(s: Any) -> None:
        nonlocal fallback_used
        source_id = s.source_series_id or s.canonical_id
        got = False
        route_attempts: list[dict[str, Any]] = []
        series_started_at = utc_now()
        series_t0 = time.perf_counter()
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            with result_lock:
                failed_series.append(source_id)
                deadline_skipped_series.append(source_id)
                series_attempts[source_id] = [
                    {
                        "provider": "harvester.budget",
                        "reason": "deadline",
                        "error": "global_acquisition_budget_exceeded",
                        "outcome": "failed",
                    }
                ]
                acquisition_sources.append(
                    source_record(
                        source_id=source_id,
                        series_id=str(s.canonical_id),
                        started_at=series_started_at,
                        t0=series_t0,
                        attempts=0,
                        outcome="failed",
                    )
                )
            return
        for provider_name in route(s.provider_priority):
            if provider_name not in enabled:
                continue
            try:
                with result_lock:
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
                with result_lock:
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
                with result_lock:
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
                with result_lock:
                    all_results.append(normalized)
                    succeeded_series.append(source_id)
                    providers_used.add(provider_identity)
                    series_providers[source_id] = provider_identity
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
            with result_lock:
                errors.append({
                    "provider": provider_name,
                    "series_id": source_id,
                    "error": result.fetch_error or "unknown",
                    "fallback_reason": result.fetch_fallback_reason,
                })
        with result_lock:
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

    from harvester.core.concurrent_policy import (
        ETF_MAX_WORKERS,
        FRED_MAX_WORKERS,
        concurrent_enabled,
        family_for_priority,
    )

    if concurrent_enabled() and requested_specs:
        fred_specs = [s for s in requested_specs if family_for_priority(s.provider_priority) == "fred"]
        etf_specs = [s for s in requested_specs if family_for_priority(s.provider_priority) == "etf"]
        other_specs = [s for s in requested_specs if family_for_priority(s.provider_priority) == "other"]
        for spec in other_specs:
            _consume_spec(spec)
        futures = []
        with ThreadPoolExecutor(max_workers=FRED_MAX_WORKERS) as fred_pool:
            with ThreadPoolExecutor(max_workers=ETF_MAX_WORKERS) as etf_pool:
                futures.extend(fred_pool.submit(_consume_spec, spec) for spec in fred_specs)
                futures.extend(etf_pool.submit(_consume_spec, spec) for spec in etf_specs)
                for future in as_completed(futures):
                    future.result()
    else:
        for spec in requested_specs:
            _consume_spec(spec)

    if not requested_series:
        outcome = make_outcome(
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

    if deadline_skipped_series:
        outcome["carry_forward_reason"] = "deadline"
        outcome["deadline_skipped_series"] = sorted(set(deadline_skipped_series))

    if not all_results:
        logger.warning("fetch_official_series_from_registry: no data returned")
        empty = pd.DataFrame(columns=[
            "date", "series_id", "source_id", "source_series_id",
            "value", "unit", "frequency", "vintage_date", "quality_flag",
        ])
        empty.attrs["provider_outcome"] = outcome
        empty.attrs["acquisition_sources"] = acquisition_sources
        empty.attrs["deadline_skipped_series"] = list(deadline_skipped_series)
        return empty

    panel = pd.concat(all_results, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.sort_values(["series_id", "date"]).reset_index(drop=True)
    panel.attrs["provider_outcome"] = outcome
    panel.attrs["acquisition_sources"] = acquisition_sources
    panel.attrs["deadline_skipped_series"] = list(deadline_skipped_series)
    return panel

__all__ = ["fetch_official_series", "fetch_official_series_from_registry"]
