"""ETF price provider via yfinance.

Acquires daily OHLCV data for ETF tickers.  This is the Harvester path
for ETF data — root scripts must not call yfinance directly.

Usage:
    provider = EtfYfinanceProvider()
    results = provider.fetch_series(["SPY", "HYG", "TLT"])
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

# Yahoo rate-limits bursty sequential downloads.  The provider therefore uses
# one bounded batch request, a very small individual retry budget, and a
# persistent provider-wide cooldown.  A failed batch must never fan out into
# 33 x 3 additional requests.
_FETCH_ATTEMPTS = 2  # one initial request + one bounded retry
_RETRY_BASE_SLEEP_S = 0.75
_INTER_TICKER_SLEEP_S = 0.2
_MAX_INDIVIDUAL_TICKERS = 3
_DEFAULT_COOLDOWN_S = 15 * 60
_DEFAULT_CACHE_MAX_AGE_S = 15 * 60
_STATE_FILENAME = "provider_state/yfinance.json"
_LOCK_FILENAME = "provider_state/yfinance.lock"
_NORMALIZATION_PROFILE = "etf_ohlcv.adjusted.v1"


def _source_signature(*, cache_hit: bool = False) -> dict[str, Any]:
    return {
        "provider": "yfinance",
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


def _is_rate_limit_error(error: BaseException | str) -> bool:
    """Classify Yahoo throttling without depending on yfinance internals."""
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "too many requests",
            "rate limit",
            "rate-limited",
            "ratelimit",
            "http 429",
            "status code 429",
            " 429",
        )
    )


def _cache_max_age_s() -> float:
    return _env_float("YFINANCE_CACHE_MAX_AGE_S", _DEFAULT_CACHE_MAX_AGE_S)


class _ProviderCooldown(RuntimeError):
    def __init__(self, until: float) -> None:
        self.until = until
        super().__init__(f"yfinance provider cooldown active until {until:.0f}")


class _YFinanceGate:
    """Persistent, cross-process single-flight and cooldown guard.

    The state file is operational evidence, not canonical market data.  If a
    restricted/read-only environment cannot persist it, the in-process lock
    still prevents concurrent calls and the provider remains usable.
    """

    _thread_lock = threading.Lock()

    def __init__(self, data_root: Path) -> None:
        self._state_path = data_root / _STATE_FILENAME
        self._lock_path = data_root / _LOCK_FILENAME
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
            logger.warning("Unable to persist yfinance provider state", exc_info=True)

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
                    # The in-process lock remains active on platforms without
                    # fcntl or when the filesystem does not support locking.
                    pass
            except OSError:
                self._lock_handle = None

            state = self._read_state()
            try:
                until = float(state.get("cooldown_until", 0) or 0)
            except (TypeError, ValueError):
                until = 0.0
            now = time.time()
            if until > now:
                raise _ProviderCooldown(until)
            try:
                last_request_at = float(state.get("last_request_at", 0) or 0)
            except (TypeError, ValueError):
                last_request_at = 0.0
            min_interval = _env_float("YFINANCE_MIN_INTERVAL_S", 1.0)
            wait_s = last_request_at + min_interval - now
            if wait_s > 0:
                time.sleep(wait_s)
            state["last_request_at"] = time.time()
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

    def mark_rate_limited(self, error: str) -> float:
        now = time.time()
        state = self._read_state()
        previous_failures = int(state.get("failure_count", 0) or 0)
        base_cooldown_s = _env_float("YFINANCE_COOLDOWN_S", _DEFAULT_COOLDOWN_S)
        max_cooldown_s = _env_float(
            "YFINANCE_BACKOFF_MAX_S",
            max(base_cooldown_s, base_cooldown_s * 8),
        )
        cooldown_s = min(
            base_cooldown_s * (2 ** min(previous_failures, 6)),
            max(max_cooldown_s, base_cooldown_s),
        )
        until = now + cooldown_s
        self._write_state(
            {
                "provider": "yfinance",
                "state": "cooldown",
                "cooldown_until": until,
                "failure_count": previous_failures + 1,
                "backoff_s": cooldown_s,
                "last_error": str(error)[:500],
                "last_request_at": state.get("last_request_at", now),
                "updated_at": now,
            }
        )
        logger.warning(
            "yfinance rate limit detected; suppressing new requests for %.0fs",
            cooldown_s,
        )
        return until

    def mark_success(self) -> None:
        state = self._read_state()
        if not state:
            return
        self._write_state(
            {
                "provider": "yfinance",
                "state": "ready",
                "cooldown_until": 0,
                "failure_count": 0,
                "last_request_at": state.get("last_request_at", 0),
                "last_success_at": time.time(),
            }
        )

# Default tickers for the structural deformation research system.
DEFAULT_ETF_TICKERS: dict[str, str] = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "HYG": "High Yield Corporate Bond ETF",
    "LQD": "Investment Grade Corporate Bond ETF",
    "TLT": "20+ Year Treasury Bond ETF",
    "IWM": "Russell 2000 ETF",
    "XLF": "Financial Select Sector ETF",
    "GLD": "Gold Trust ETF",
    "UUP": "US Dollar Index Bullish ETF",
    "XLE": "Energy Select Sector ETF",
    "XLK": "Technology Select Sector ETF",
    "XLV": "Health Care Select Sector ETF",
    "XLI": "Industrial Select Sector ETF",
    "XLP": "Consumer Staples Select Sector ETF",
    "XLY": "Consumer Discretionary Select Sector ETF",
    "XLU": "Utilities Select Sector ETF",
    "XLRE": "Real Estate Select Sector ETF",
    "XLB": "Materials Select Sector ETF",
    "EEM": "Emerging Markets ETF",
    "EFA": "EAFE ETF",
    "FXI": "China Large-Cap ETF",
    "EWJ": "Japan ETF",
    "TIP": "TIPS Bond ETF",
    "SHY": "1-3 Year Treasury Bond ETF",
    "IEF": "7-10 Year Treasury Bond ETF",
    "AGG": "US Aggregate Bond ETF",
    "BIL": "1-3 Month T-Bill ETF",
    "VXX": "VIX Short-Term Futures ETF",
    "DJP": "Commodity Index ETF",
    "USO": "Oil Fund ETF",
    "VNQ": "Real Estate ETF",
    "GDX": "Gold Miners ETF",
    # K channel: options-derived tail risk indices
    "^SKEW": "CBOE SKEW Index (tail risk pricing)",
    "^VVIX": "CBOE VVIX (volatility of VIX)",
}


class EtfYfinanceProvider(OfficialProvider):
    """ETF daily OHLCV acquisition via yfinance.

    No API key required.  Data is fetched from Yahoo Finance.
    """

    source_id = "yfinance"

    def __init__(
        self,
        tickers: dict[str, str] | None = None,
        period: str = "60d",
        data_root: str = "",
        cache: bool = True,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
        **_: Any,
    ) -> None:
        super().__init__(data_root=data_root, cache=cache, user_agent=user_agent)
        self._tickers = tickers or DEFAULT_ETF_TICKERS
        self._period = period
        self._gate = _YFinanceGate(self._data_root)
        self._last_batch_kind = ""
        self._last_batch_error = ""

    def fetch_series(self, series_ids: list[str] | None = None) -> list[ProviderResult]:
        if series_ids is None:
            series_ids = list(self._tickers.keys())
        if not series_ids:
            return []

        requested = list(dict.fromkeys(series_ids))
        try:
            with self._gate.claim():
                by_id = self._fetch_batch(requested)
                missing = [
                    ticker
                    for ticker in requested
                    if by_id.get(ticker) is None or by_id[ticker].empty()
                ]
                rate_limited = False

                # An empty/rate-limited batch is a provider-wide failure.  Do
                # not turn it into a request storm by probing every ticker.
                if missing and self._last_batch_kind in {"rate_limited", "empty_batch"}:
                    reason = (
                        "provider_cooldown"
                        if self._last_batch_kind == "rate_limited"
                        else "batch_empty_no_fanout"
                    )
                    if self._last_batch_kind == "rate_limited":
                        self._gate.mark_rate_limited(self._last_batch_error)
                    return [
                        by_id.get(ticker)
                        or self._build_error_result(
                            ticker,
                            self._last_batch_error
                            or f"yfinance batch returned no data for {ticker}",
                            reason,
                        )
                        for ticker in requested
                    ]

                if missing:
                    retry_tickers = missing[:_MAX_INDIVIDUAL_TICKERS]
                    logger.warning(
                        "ETF batch incomplete; retrying %d/%d missing tickers individually",
                        len(retry_tickers),
                        len(missing),
                    )
                    for index, ticker in enumerate(retry_tickers):
                        if index:
                            time.sleep(_INTER_TICKER_SLEEP_S)
                        result = self._fetch_one(ticker)
                        by_id[ticker] = result
                        if result.fetch_fallback_reason == "rate_limited":
                            self._gate.mark_rate_limited(result.fetch_error or "rate limited")
                            rate_limited = True
                            break

                    # The remainder was deliberately not probed.  Preserve a
                    # typed result so downstream manifests can explain the
                    # bounded retry budget rather than hiding missing rows.
                    for ticker in missing:
                        by_id.setdefault(
                            ticker,
                            self._build_error_result(
                                ticker,
                                f"retry budget exhausted for {ticker}",
                                "retry_budget_exhausted",
                            ),
                        )

                if not rate_limited and any(
                    result is not None and not result.empty()
                    for result in by_id.values()
                ):
                    self._gate.mark_success()
                return [
                    by_id.get(ticker)
                    or self._build_error_result(ticker, "missing provider result", "empty")
                    for ticker in requested
                ]
        except _ProviderCooldown as exc:
            logger.warning("Skipping yfinance request: %s", exc)
            return [
                self._build_error_result(
                    ticker,
                    str(exc),
                    "provider_cooldown",
                )
                for ticker in requested
            ]

    def _frame_from_ohlcv(self, data: pd.DataFrame) -> pd.DataFrame:
        if isinstance(data.columns, pd.MultiIndex):
            data = data.copy()
            data.columns = data.columns.get_level_values(0)
        frame = pd.DataFrame(
            {
                "date": data.index,
                "value": data["Close"].values,
                "open": data["Open"].values,
                "high": data["High"].values,
                "low": data["Low"].values,
                "volume": data["Volume"].values,
                "unit": "USD",
                "frequency": "daily",
            }
        )
        return frame.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

    def _result_from_frame(self, ticker: str, frame: pd.DataFrame) -> ProviderResult:
        return self._result_from_frame_with_cache(ticker, frame, persist=self._cache)

    def _result_from_frame_with_cache(
        self,
        ticker: str,
        frame: pd.DataFrame,
        *,
        persist: bool,
        cache_hit: bool = False,
    ) -> ProviderResult:
        if persist:
            self._write_raw(ticker, frame.to_json(orient="records", date_format="iso"))
        return ProviderResult(
            provider=self.source_id,
            series_id=ticker,
            frame=frame,
            source_url=f"https://finance.yahoo.com/quote/{ticker}",
            source_params={
                "period": self._period,
                "adjusted": True,
                "source_signature": _source_signature(cache_hit=cache_hit),
            },
            data_note=f"yfinance daily OHLCV for {self._tickers.get(ticker, ticker)}",
        )

    def _read_cached_result(self, ticker: str) -> ProviderResult | None:
        if not self._cache:
            return None
        path = self._raw_dir() / f"{ticker}_raw.json"
        try:
            age = max(0.0, time.time() - path.stat().st_mtime)
            if age > _cache_max_age_s():
                return None
            frame = pd.read_json(path)
        except (OSError, ValueError, TypeError):
            return None
        if frame.empty or "date" not in frame.columns:
            return None
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).reset_index(drop=True)
        if frame.empty:
            return None
        return self._result_from_frame_with_cache(ticker, frame, persist=False, cache_hit=True)

    def _fetch_batch(self, series_ids: list[str]) -> dict[str, ProviderResult]:
        """One multi-ticker download — fewer Yahoo round-trips than N serial calls."""
        out: dict[str, ProviderResult] = {}
        self._last_batch_kind = ""
        self._last_batch_error = ""
        uncached: list[str] = []
        for ticker in series_ids:
            cached = self._read_cached_result(ticker)
            if cached is None:
                uncached.append(ticker)
            else:
                out[ticker] = cached
        if not uncached:
            self._last_batch_kind = "cache"
            return out
        try:
            import yfinance as yf
        except ImportError:
            self._last_batch_kind = "missing_dependency"
            self._last_batch_error = "yfinance not installed"
            for ticker in uncached:
                out[ticker] = self._build_error_result(
                    ticker, "yfinance not installed", "missing_dependency"
                )
            return out

        try:
            # threads=False: launchd soft NOFILE is often ~256; threaded
            # Yahoo fetches open many sockets and trip EMFILE (errno 24).
            data = yf.download(
                uncached,
                period=self._period,
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=False,
            )
        except Exception as exc:
            logger.warning("ETF batch download failed: %s", exc)
            self._last_batch_error = f"yfinance batch error: {exc}"
            self._last_batch_kind = "rate_limited" if _is_rate_limit_error(exc) else "fetch_error"
            return out

        if data is None or data.empty:
            self._last_batch_error = "yfinance batch returned no data"
            self._last_batch_kind = "empty_batch"
            return out

        multi = isinstance(data.columns, pd.MultiIndex)
        for ticker in uncached:
            try:
                if multi:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    ticker_df = data[ticker].dropna(how="all")
                else:
                    # Single-ticker response shape even when one id requested.
                    if len(uncached) != 1:
                        continue
                    ticker_df = data
                if ticker_df.empty or "Close" not in ticker_df.columns:
                    continue
                frame = self._frame_from_ohlcv(ticker_df)
                if frame.empty:
                    continue
                out[ticker] = self._result_from_frame(ticker, frame)
            except Exception as exc:
                logger.warning("ETF batch parse failed for %s: %s", ticker, exc)
        if not out:
            self._last_batch_error = "yfinance batch contained no usable rows"
            self._last_batch_kind = "empty_batch"
        return out

    def _fetch_one(self, ticker: str) -> ProviderResult:
        try:
            import yfinance as yf
        except ImportError:
            return self._build_error_result(ticker, "yfinance not installed", "missing_dependency")

        last_error = f"yfinance returned no data for {ticker}"
        last_kind = "empty"
        for attempt in range(_FETCH_ATTEMPTS):
            try:
                data = yf.download(ticker, period=self._period, progress=False, auto_adjust=True)
                if data.empty:
                    last_error = f"yfinance returned no data for {ticker}"
                    last_kind = "empty"
                else:
                    frame = self._frame_from_ohlcv(data)
                    if frame.empty:
                        last_error = f"yfinance returned no usable rows for {ticker}"
                        last_kind = "empty"
                    else:
                        return self._result_from_frame(ticker, frame)
            except Exception as exc:
                last_error = f"yfinance error: {exc}"
                last_kind = "rate_limited" if _is_rate_limit_error(exc) else "fetch_error"

                # A 429 is provider-wide; retrying immediately only increases
                # the ban window.  The caller records the persistent cooldown.
                if last_kind == "rate_limited":
                    return self._build_error_result(ticker, last_error, last_kind)

            if attempt + 1 < _FETCH_ATTEMPTS:
                sleep_s = _RETRY_BASE_SLEEP_S * (2 ** attempt) + random.uniform(0, 0.25)
                logger.warning(
                    "ETF fetch retry %d/%d for %s after %s (sleep %.2fs)",
                    attempt + 1,
                    _FETCH_ATTEMPTS,
                    ticker,
                    last_kind,
                    sleep_s,
                )
                time.sleep(sleep_s)

        return self._build_error_result(ticker, last_error, last_kind)


__all__ = ["EtfYfinanceProvider", "DEFAULT_ETF_TICKERS"]
