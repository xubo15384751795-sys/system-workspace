"""Owned ETF market-data provider chain.

The cross-asset panel needs daily OHLCV for a small, known ETF universe.  A
single free endpoint is not a production reliability strategy, so this module
keeps the source decision inside Harvester and records the source selected for
each ticker:

    Tiingo -> Massive -> yfinance

Tiingo and Massive are optional authenticated providers.  When their keys are
absent, the chain skips them without making a network request.  yfinance stays
as a bounded last resort and retains its existing cooldown/cache guard.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from harvester.http_gateway import GatewayError, OwnedHTTPGateway
from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_MAX_AGE_S = 15 * 60
_DEFAULT_COOLDOWN_S = 15 * 60
_DEFAULT_MIN_INTERVAL_S = 0.25
_DEFAULT_CHAIN = ("tiingo", "massive", "yfinance")
_API_KEY_ENV = {
    "tiingo": "TIINGO_API_KEY",
    "massive": "MASSIVE_API_KEY",
}
_NORMALIZATION_PROFILE = "etf_ohlcv.adjusted.v1"


def _source_signature(provider: str, *, cache_hit: bool = False) -> dict[str, Any]:
    """Describe the effective measurement convention for one provider.

    Provider names alone are not enough to detect source drift.  The signature
    records the adjustment and trading-date normalization choices that must be
    held constant (or explicitly compared) when a fallback changes source.
    """
    return {
        "provider": str(provider),
        "normalization_profile": _NORMALIZATION_PROFILE,
        "adjusted": True,
        "timestamp_basis": "trading_date",
        "cache_hit": bool(cache_hit),
    }


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using %.1fs", name, raw, default)
        return default


def _period_days(period: str) -> int:
    """Translate the small period vocabulary used by the existing provider."""
    text = str(period or "5d").strip().lower()
    digits = "".join(ch for ch in text if ch.isdigit())
    try:
        value = max(1, int(digits or "5"))
    except ValueError:
        value = 5
    if text.endswith("y"):
        value *= 365
    elif text.endswith("m"):
        value *= 30
    elif text.endswith("w"):
        value *= 7
    return min(value, 3650)


def _date_window(period: str) -> tuple[str, str]:
    # Add calendar slack so a request for N trading days spans weekends and
    # holidays without making the provider-specific routes invent calendars.
    days = _period_days(period)
    end = date.today()
    start = end - timedelta(days=max(7, days * 2 + 5))
    return start.isoformat(), end.isoformat()


def _api_key(provider: str, explicit: str | None = None) -> str:
    if explicit:
        return str(explicit).strip()
    env_name = _API_KEY_ENV.get(provider, "")
    value = os.environ.get(env_name, "").strip() if env_name else ""
    return value


def _cache_max_age_s() -> float:
    return _env_float("ETF_PROVIDER_CACHE_MAX_AGE_S", _DEFAULT_CACHE_MAX_AGE_S)


def _looks_rate_limited(status_code: int, body: str = "") -> bool:
    text = body.lower()
    return status_code == 429 or any(
        marker in text
        for marker in ("too many requests", "rate limit", "rate-limited", "ratelimit")
    )


_RETRYABLE_ATTEMPT_REASONS = frozenset(
    {
        "rate_limited",
        "provider_cooldown",
        "transport_error",
        "provider_call_failed",
        "empty",
        "batch_empty_no_fanout",
        "retry_budget_exhausted",
    }
)

ATTEMPT_FAILURE_CLASSES = frozenset(
    {
        "NONE",
        "NO_DATA",
        "PROVIDER_DOWN",
        "NETWORK",
        "SCHEMA_CHANGED",
        "PARSER",
        "PERMISSION",
        "RATE_LIMIT",
        "UNKNOWN",
    }
)


def _attempt_failure_class(*, reason: str, error: str, outcome: str) -> str:
    """Map provider-specific reason text to a stable downstream category."""
    if str(outcome or "").lower() == "success":
        return "NONE"
    text = f"{reason} {error}".lower()
    if any(marker in text for marker in ("rate", "429", "too many", "throttle")):
        return "RATE_LIMIT"
    if any(marker in text for marker in ("schema", "column", "field", "shape")):
        return "SCHEMA_CHANGED"
    if any(marker in text for marker in ("parse", "decode", "json", "normalize")):
        return "PARSER"
    if any(marker in text for marker in ("permission", "unauthorized", "forbidden", "401", "403", "api key")):
        return "PERMISSION"
    if any(marker in text for marker in ("empty", "no data", "no result", "not found")):
        return "NO_DATA"
    if any(marker in text for marker in ("transport", "network", "timeout", "connection", "dns")):
        return "NETWORK"
    if any(marker in text for marker in ("provider", "cooldown", "init", "call failed")):
        return "PROVIDER_DOWN"
    return "UNKNOWN"


def _provider_attempt_record(
    *,
    provider: str,
    series_id: str,
    attempt_number: int,
    source_tier: int,
    reason: str,
    error: str = "",
    outcome: str = "failed",
) -> dict[str, Any]:
    """Build a secret-free, stable provider attempt record.

    This is deliberately a provenance-side identity (``att_``), not a new
    member of the frozen Observation -> Measurement -> Evidence -> Claim
    canonical ID chain. The release and series context scope the record.
    """
    identity = "|".join(
        [str(provider), str(series_id), str(attempt_number), str(source_tier), str(reason)]
    ).encode("utf-8")
    attempt_id = "att_" + hashlib.sha256(identity).hexdigest()[:32]
    return {
        "provider_attempt_id": attempt_id,
        "attempt_number": int(attempt_number),
        "provider": str(provider),
        "source_tier": int(source_tier),
        "reason": str(reason or "unknown")[:120],
        "error": str(error or "")[:300],
        "outcome": str(outcome or "failed"),
        "retryable": str(reason or "") in _RETRYABLE_ATTEMPT_REASONS,
        "failure_class": _attempt_failure_class(
            reason=reason,
            error=error,
            outcome=outcome,
        ),
    }


class _ProviderCooldown(RuntimeError):
    def __init__(self, provider: str, until: float) -> None:
        self.provider = provider
        self.until = until
        super().__init__(f"{provider} provider cooldown active until {until:.0f}")


class _ProviderGate:
    """Small persistent gate shared by each authenticated provider."""

    _thread_lock = threading.Lock()

    def __init__(self, provider: str, data_root: Path) -> None:
        self._provider = provider
        self._state_path = data_root / "provider_state" / f"{provider}.json"
        self._lock_path = data_root / "provider_state" / f"{provider}.lock"
        self._lock_handle: Any | None = None

    def _read_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_state(self, payload: dict[str, Any]) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self._state_path)
        except OSError:
            logger.warning("Unable to persist %s provider state", self._provider, exc_info=True)

    @contextmanager
    def claim(self):
        self._thread_lock.acquire()
        try:
            try:
                self._lock_path.parent.mkdir(parents=True, exist_ok=True)
                self._lock_handle = self._lock_path.open("a+", encoding="utf-8")
                try:
                    import fcntl

                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX)
                except (ImportError, OSError):
                    pass
            except OSError:
                self._lock_handle = None

            state = self._read_state()
            try:
                cooldown_until = float(state.get("cooldown_until", 0) or 0)
            except (TypeError, ValueError):
                cooldown_until = 0.0
            now = time.time()
            if cooldown_until > now:
                raise _ProviderCooldown(self._provider, cooldown_until)
            try:
                last_request_at = float(state.get("last_request_at", 0) or 0)
            except (TypeError, ValueError):
                last_request_at = 0.0
            wait_s = last_request_at + _env_float(
                f"{self._provider.upper()}_MIN_INTERVAL_S", _DEFAULT_MIN_INTERVAL_S
            ) - now
            if wait_s > 0:
                time.sleep(wait_s)
            state["last_request_at"] = time.time()
            state["provider"] = self._provider
            self._write_state(state)
            yield
        finally:
            if self._lock_handle is not None:
                try:
                    import fcntl

                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass
                try:
                    self._lock_handle.close()
                except OSError:
                    pass
                self._lock_handle = None
            self._thread_lock.release()

    def mark_rate_limited(self, error: str) -> None:
        now = time.time()
        state = self._read_state()
        previous_failures = int(state.get("failure_count", 0) or 0)
        base_cooldown_s = _env_float(
            f"{self._provider.upper()}_COOLDOWN_S", _DEFAULT_COOLDOWN_S
        )
        max_cooldown_s = _env_float(
            f"{self._provider.upper()}_BACKOFF_MAX_S",
            max(base_cooldown_s, base_cooldown_s * 8),
        )
        cooldown_s = min(
            base_cooldown_s * (2 ** min(previous_failures, 6)),
            max(max_cooldown_s, base_cooldown_s),
        )
        self._write_state(
            {
                "provider": self._provider,
                "state": "cooldown",
                "cooldown_until": now + cooldown_s,
                "failure_count": previous_failures + 1,
                "backoff_s": cooldown_s,
                "last_error": str(error)[:500],
                "last_request_at": state.get("last_request_at", now),
                "updated_at": now,
            }
        )
        logger.warning(
            "%s rate limit detected; suppressing new requests for %.0fs",
            self._provider,
            cooldown_s,
        )

    def mark_success(self) -> None:
        state = self._read_state()
        self._write_state(
            {
                "provider": self._provider,
                "state": "ready",
                "cooldown_until": 0,
                "failure_count": 0,
                "last_request_at": state.get("last_request_at", 0),
                "last_success_at": time.time(),
            }
        )


def _normalise_frame(
    rows: list[Mapping[str, Any]],
    *,
    provider: str,
    ticker: str,
    timestamp_field: str = "date",
    adjusted: bool = True,
) -> pd.DataFrame:
    """Normalize provider-native rows to the Harvester ETF shape."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        try:
            timestamp = row.get(timestamp_field)
            if timestamp_field == "t":
                timestamp = pd.to_datetime(timestamp, unit="ms", utc=True).tz_convert(
                    "America/New_York"
                ).tz_localize(None)
            else:
                timestamp = pd.to_datetime(timestamp, errors="coerce")
                if getattr(timestamp, "tzinfo", None) is not None:
                    timestamp = timestamp.tz_convert(None)
            if pd.isna(timestamp):
                continue

            def value(name: str, adjusted_name: str | None = None, default: Any = 0.0) -> Any:
                if adjusted and adjusted_name and row.get(adjusted_name) is not None:
                    return row.get(adjusted_name)
                return row.get(name, default)

            normalized.append(
                {
                    "date": timestamp,
                    "value": float(value("c" if provider == "massive" else "close", "adjClose")),
                    "open": float(value("o" if provider == "massive" else "open", "adjOpen")),
                    "high": float(value("h" if provider == "massive" else "high", "adjHigh")),
                    "low": float(value("l" if provider == "massive" else "low", "adjLow")),
                    "volume": float(value("v" if provider == "massive" else "volume", "adjVolume")),
                    "unit": "USD",
                    "frequency": "daily",
                }
            )
        except (TypeError, ValueError, OverflowError):
            logger.warning("%s returned an unparseable row for %s", provider, ticker)
    if not normalized:
        return pd.DataFrame(
            columns=["date", "value", "open", "high", "low", "volume", "unit", "frequency"]
        )
    frame = pd.DataFrame(normalized)
    return frame.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)


class _AuthenticatedEodProvider(OfficialProvider):
    source_id = ""
    endpoint_id = ""
    key_env = ""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        period: str = "5d",
        data_root: str | Path = "",
        cache: bool = True,
        gateway: OwnedHTTPGateway | None = None,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
        **_: Any,
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._period = period
        self._api_key = _api_key(self.source_id, api_key)
        self._gateway = gateway or OwnedHTTPGateway(
            headers={
                "Accept": "application/json",
                "User-Agent": user_agent,
                "Authorization": self._authorization_header(),
            }
        )
        self._gate = _ProviderGate(self.source_id, self._data_root)

    def _authorization_header(self) -> str:
        raise NotImplementedError

    def _request_params(self, ticker: str, start_date: str, end_date: str) -> dict[str, object]:
        raise NotImplementedError

    def _parse_payload(self, payload: Any, ticker: str) -> list[Mapping[str, Any]]:
        raise NotImplementedError

    def _source_url(self, ticker: str) -> str:
        raise NotImplementedError

    def fetch_series(self, series_ids: list[str] | None = None) -> list[ProviderResult]:
        requested = list(dict.fromkeys(series_ids or []))
        if not requested:
            return []
        results: list[ProviderResult] = []
        cooldown = False
        for index, ticker in enumerate(requested):
            if cooldown:
                results.append(
                    self._build_error_result(
                        ticker,
                        f"{self.source_id} request budget stopped after provider throttling",
                        "provider_cooldown",
                    )
                )
                continue
            cached = self._read_cached_result(ticker)
            if cached is not None:
                results.append(cached)
                continue
            if not self._api_key:
                results.append(
                    self._build_error_result(
                        ticker,
                        f"missing {self.source_id} API key",
                        "missing_api_key",
                    )
                )
                continue
            if index:
                # The persistent gate also enforces this across processes; the
                # short sleep prevents a single batch from being bursty.
                time.sleep(_env_float(f"{self.source_id.upper()}_MIN_INTERVAL_S", _DEFAULT_MIN_INTERVAL_S))
            result = self._fetch_one(ticker)
            results.append(result)
            if result.fetch_fallback_reason == "rate_limited":
                self._gate.mark_rate_limited(result.fetch_error or "rate limited")
                cooldown = True
            elif not result.empty() and not result.fetch_error:
                self._gate.mark_success()
        return results

    def _fetch_one(self, ticker: str) -> ProviderResult:
        start_date, end_date = _date_window(self._period)
        try:
            with self._gate.claim():
                response = self._gateway.fetch(
                    self.source_id,
                    self.endpoint_id,
                    self._request_params(ticker, start_date, end_date),
                )
        except _ProviderCooldown as exc:
            return self._build_error_result(ticker, str(exc), "provider_cooldown")
        except GatewayError as exc:
            return self._build_error_result(ticker, str(exc), "transport_error")

        body = response.text
        if _looks_rate_limited(response.status_code, body):
            return self._build_error_result(
                ticker,
                f"{self.source_id} response status={response.status_code}",
                "rate_limited",
            )
        if response.status_code in {401, 403}:
            return self._build_error_result(
                ticker,
                f"{self.source_id} authentication rejected",
                "authentication_failed",
            )
        if not 200 <= response.status_code < 300:
            return self._build_error_result(
                ticker,
                f"{self.source_id} response status={response.status_code}",
                f"http_{response.status_code}",
            )
        try:
            payload = response.json()
            rows = self._parse_payload(payload, ticker)
            frame = _normalise_frame(
                rows,
                provider=self.source_id,
                ticker=ticker,
                timestamp_field="t" if self.source_id == "massive" else "date",
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._build_error_result(
                ticker,
                f"{self.source_id} response parse failed: {exc}",
                "parse_error",
            )
        if frame.empty:
            return self._build_error_result(
                ticker,
                f"{self.source_id} returned no usable rows",
                "empty",
            )
        if self._cache:
            self._write_raw(ticker, response.content)
        return ProviderResult(
            provider=self.source_id,
            series_id=ticker,
            frame=frame,
            source_url=self._source_url(ticker),
            source_params={
                "start_date": start_date,
                "end_date": end_date,
                "adjusted": True,
                "source_signature": _source_signature(self.source_id),
            },
            data_note=f"{self.source_id} daily ETF OHLCV",
        )

    def _read_cached_result(self, ticker: str) -> ProviderResult | None:
        if not self._cache:
            return None
        path = self._raw_dir() / f"{ticker}_raw.json"
        try:
            age = max(0.0, time.time() - path.stat().st_mtime)
            if age > _cache_max_age_s():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = self._parse_payload(payload, ticker)
            frame = _normalise_frame(
                rows,
                provider=self.source_id,
                ticker=ticker,
                timestamp_field="t" if self.source_id == "massive" else "date",
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        if frame.empty:
            return None
        return ProviderResult(
            provider=self.source_id,
            series_id=ticker,
            frame=frame,
            source_url=self._source_url(ticker),
            source_params={
                "cache_hit": True,
                "cache_age_seconds": round(age, 3),
                "adjusted": True,
                "source_signature": _source_signature(self.source_id, cache_hit=True),
            },
            data_note=f"{self.source_id} daily ETF OHLCV (recent raw cache)",
        )


class TiingoEodProvider(_AuthenticatedEodProvider):
    """Tiingo daily OHLCV provider."""

    source_id = "tiingo"
    endpoint_id = "daily_prices"

    def _authorization_header(self) -> str:
        return f"Token {self._api_key}" if self._api_key else ""

    def _request_params(self, ticker: str, start_date: str, end_date: str) -> dict[str, object]:
        return {"ticker": ticker, "startDate": start_date, "endDate": end_date}

    def _parse_payload(self, payload: Any, ticker: str) -> list[Mapping[str, Any]]:
        if not isinstance(payload, list):
            raise TypeError(f"{self.source_id} payload for {ticker} is not a list")
        return [item for item in payload if isinstance(item, Mapping)]

    def _source_url(self, ticker: str) -> str:
        return f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"


class MassiveEodProvider(_AuthenticatedEodProvider):
    """Massive daily aggregate provider."""

    source_id = "massive"
    endpoint_id = "daily_aggs"

    def _authorization_header(self) -> str:
        return f"Bearer {self._api_key}" if self._api_key else ""

    def _request_params(self, ticker: str, start_date: str, end_date: str) -> dict[str, object]:
        return {
            "ticker": ticker,
            "from_date": start_date,
            "to_date": end_date,
            "multiplier": "1",
            "timespan": "day",
            "adjusted": True,
            "sort": "asc",
        }

    def _parse_payload(self, payload: Any, ticker: str) -> list[Mapping[str, Any]]:
        if not isinstance(payload, Mapping):
            raise TypeError(f"{self.source_id} payload for {ticker} is not an object")
        rows = payload.get("results", [])
        if not isinstance(rows, list):
            raise TypeError(f"{self.source_id} results for {ticker} is not a list")
        return [item for item in rows if isinstance(item, Mapping)]

    def _source_url(self, ticker: str) -> str:
        return f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day"


ProviderFactory = Callable[..., OfficialProvider]


class EtfProviderChain(OfficialProvider):
    """Select the first healthy ETF provider per ticker."""

    source_id = "etf_provider_chain"

    def __init__(
        self,
        *,
        tickers: dict[str, str] | None = None,
        period: str = "5d",
        data_root: str | Path = "",
        cache: bool = True,
        provider_order: tuple[str, ...] | list[str] | None = None,
        provider_instances: Mapping[str, OfficialProvider] | None = None,
        provider_factories: Mapping[str, ProviderFactory] | None = None,
        api_keys: Mapping[str, str] | None = None,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
        **_: Any,
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._tickers = tickers or {}
        self._period = period
        configured = provider_order or tuple(
            item.strip().lower()
            for item in os.environ.get("ETF_PROVIDER_CHAIN", ",".join(_DEFAULT_CHAIN)).split(",")
            if item.strip()
        )
        self.provider_order = tuple(dict.fromkeys(configured)) or _DEFAULT_CHAIN
        self._instances = dict(provider_instances or {})
        self._factories = dict(provider_factories or {})
        self._api_keys = dict(api_keys or {})
        self._user_agent = user_agent

    def _provider(self, name: str) -> OfficialProvider:
        if name in self._instances:
            return self._instances[name]
        if name in self._factories:
            self._instances[name] = self._factories[name](
                tickers=self._tickers,
                period=self._period,
                data_root=str(self._data_root),
                cache=self._cache,
                api_key=self._api_keys.get(name),
                user_agent=self._user_agent,
            )
            return self._instances[name]
        if name == "tiingo":
            self._instances[name] = TiingoEodProvider(
                api_key=self._api_keys.get(name),
                period=self._period,
                data_root=self._data_root,
                cache=self._cache,
                user_agent=self._user_agent,
            )
        elif name == "massive":
            self._instances[name] = MassiveEodProvider(
                api_key=self._api_keys.get(name),
                period=self._period,
                data_root=self._data_root,
                cache=self._cache,
                user_agent=self._user_agent,
            )
        elif name == "yfinance":
            from harvester.providers.etf_yfinance import EtfYfinanceProvider

            self._instances[name] = EtfYfinanceProvider(
                tickers=self._tickers,
                period=self._period,
                data_root=str(self._data_root),
                cache=self._cache,
                user_agent=self._user_agent,
            )
        else:
            raise ValueError(f"unsupported ETF provider: {name}")
        return self._instances[name]

    def fetch_series(self, series_ids: list[str] | None = None) -> list[ProviderResult]:
        requested = list(dict.fromkeys(series_ids or self._tickers.keys()))
        if not requested:
            return []
        selected: dict[str, ProviderResult] = {}
        attempts: dict[str, list[dict[str, Any]]] = {ticker: [] for ticker in requested}
        remaining = list(requested)
        for provider_index, provider_name in enumerate(self.provider_order, start=1):
            if not remaining:
                break
            try:
                provider = self._provider(provider_name)
            except Exception as exc:
                for ticker in remaining:
                    attempts[ticker].append(
                        _provider_attempt_record(
                            provider=provider_name,
                            series_id=ticker,
                            attempt_number=len(attempts[ticker]) + 1,
                            source_tier=provider_index,
                            reason="provider_init_failed",
                            error=str(exc),
                        )
                    )
                continue
            provider_call_error = ""
            try:
                results = provider.fetch_series(remaining)
            except Exception as exc:
                results = []
                provider_call_error = str(exc)
                logger.warning("ETF provider %s failed before returning results: %s", provider_name, exc)
            by_id = {str(result.series_id): result for result in results}
            next_remaining: list[str] = []
            for ticker in remaining:
                if provider_call_error:
                    attempts[ticker].append(
                        _provider_attempt_record(
                            provider=provider_name,
                            series_id=ticker,
                            attempt_number=len(attempts[ticker]) + 1,
                            source_tier=provider_index,
                            reason="provider_call_failed",
                            error=provider_call_error,
                        )
                    )
                    next_remaining.append(ticker)
                    continue
                result = by_id.get(ticker)
                if result is not None and not result.empty():
                    success_attempt = _provider_attempt_record(
                        provider=provider_name,
                        series_id=ticker,
                        attempt_number=len(attempts[ticker]) + 1,
                        source_tier=provider_index,
                        reason="success",
                        outcome="success",
                    )
                    result.source_params = dict(result.source_params or {})
                    result.source_params.setdefault("provider_chain", list(self.provider_order))
                    result.source_params.setdefault(
                        "source_signature",
                        _source_signature(result.provider or provider_name),
                    )
                    if provider_name == "yfinance":
                        # yfinance is continuity/diagnostic evidence only. It
                        # remains useful for a degraded panel, but its route
                        # must be visible to admission and promotion layers.
                        result.source_params["diagnostic_only"] = True
                        result.source_params["claim_ceiling"] = "diagnostic_only"
                    if provider_name != self.provider_order[0]:
                        result.source_params["fallback_from"] = list(self.provider_order[: self.provider_order.index(provider_name)])
                        if not result.fetch_fallback_reason:
                            result.fetch_fallback_reason = "provider_chain_fallback"
                    result.source_params["provider_attempts"] = [
                        *attempts[ticker],
                        success_attempt,
                    ]
                    selected[ticker] = result
                    continue
                failure = result or ProviderResult(
                    provider=provider_name,
                    series_id=ticker,
                    frame=pd.DataFrame(),
                    fetch_error="provider returned no result",
                    fetch_fallback_reason="empty",
                )
                attempts[ticker].append(
                    _provider_attempt_record(
                        provider=provider_name,
                        series_id=ticker,
                        attempt_number=len(attempts[ticker]) + 1,
                        source_tier=provider_index,
                        reason=failure.fetch_fallback_reason or "empty",
                        error=failure.fetch_error or "empty",
                    )
                )
                next_remaining.append(ticker)
            remaining = next_remaining

        for ticker in remaining:
            ticker_attempts = attempts[ticker]
            error = "; ".join(
                f"{item['provider']}:{item['reason']}" for item in ticker_attempts
            ) or "no provider returned a result"
            selected[ticker] = ProviderResult(
                provider=self.source_id,
                series_id=ticker,
                frame=pd.DataFrame(),
                fetch_error=error[:2000],
                fetch_fallback_reason="all_providers_failed",
                source_params={
                    "provider_chain": list(self.provider_order),
                    "provider_attempts": ticker_attempts,
                },
            )
        return [selected[ticker] for ticker in requested]


__all__ = [
    "EtfProviderChain",
    "MassiveEodProvider",
    "TiingoEodProvider",
]
