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
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

# Yahoo rate-limits bursty sequential downloads; brief spacing + retries
# recover from the empty-frame / transient-error pattern seen in daily runs.
_FETCH_ATTEMPTS = 2
_RETRY_BASE_SLEEP_S = 0.75
_INTER_TICKER_SLEEP_S = 0.2
_DEFAULT_TIMEOUT_S = 15
_DEFAULT_RATE_LIMIT_COOLDOWN_S = 6 * 60 * 60
_RATE_LIMIT_STATE_FILE = "rate_limit_state.json"

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
    "LQD": "Investment Grade Corporate Bond ETF",
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
        try:
            self._timeout = max(1, int(os.environ.get("YFINANCE_TIMEOUT_S", _DEFAULT_TIMEOUT_S)))
        except ValueError:
            self._timeout = _DEFAULT_TIMEOUT_S
        try:
            self._rate_limit_cooldown_s = max(
                0,
                int(
                    os.environ.get(
                        "YFINANCE_RATE_LIMIT_COOLDOWN_SECONDS",
                        _DEFAULT_RATE_LIMIT_COOLDOWN_S,
                    )
                ),
            )
        except ValueError:
            self._rate_limit_cooldown_s = _DEFAULT_RATE_LIMIT_COOLDOWN_S

    def fetch_series(self, series_ids: list[str] | None = None) -> list[ProviderResult]:
        if series_ids is None:
            series_ids = list(self._tickers.keys())
        if not series_ids:
            return []

        cooldown = self._active_rate_limit_cooldown()
        if cooldown is not None:
            return [
                self._build_error_result(
                    ticker,
                    f"yfinance rate-limit cooldown active for {cooldown:.0f}s",
                    "rate_limit_cooldown",
                )
                for ticker in series_ids
            ]

        by_id = self._fetch_batch(series_ids)
        missing = [ticker for ticker in series_ids if by_id.get(ticker) is None or by_id[ticker].empty()]
        if missing:
            # A batch-level 429 is already represented for every ticker. Do
            # not probe or fan out into serial requests; that only extends the
            # provider ban and turns one source incident into a long run.
            if any(
                result.fetch_fallback_reason == "rate_limited"
                for result in by_id.values()
            ):
                for ticker in series_ids:
                    by_id.setdefault(
                        ticker,
                        self._build_error_result(
                            ticker,
                            "yfinance rate-limit cooldown entered",
                            "rate_limit_cooldown",
                        ),
                    )
                return [by_id[ticker] for ticker in series_ids]
            # A fully empty batch is usually a transport/rate-limit failure,
            # not 33 independent ticker failures. Probe once before falling
            # back to serial requests; this keeps launchd from spending hours
            # retrying the same unavailable network path.
            if not by_id:
                logger.warning(
                    "ETF batch returned no usable data; probing one ticker before fallback"
                )
                probe = self._fetch_one(missing[0], attempts=1)
                by_id[missing[0]] = probe
                missing = missing[1:]
                if probe.empty():
                    reason = probe.fetch_error or "batch and probe returned no data"
                    logger.warning(
                        "ETF acquisition unavailable after bounded probe; "
                        "skipping %d remaining tickers: %s",
                        len(missing),
                        reason,
                    )
                    for ticker in missing:
                        by_id[ticker] = self._build_error_result(
                            ticker,
                            f"ETF batch unavailable; probe failed: {reason}",
                            "batch_unavailable",
                        )
                    missing = []

            if missing:
                logger.warning("ETF batch incomplete; retrying %d tickers individually", len(missing))
                for index, ticker in enumerate(missing):
                    if index:
                        time.sleep(_INTER_TICKER_SLEEP_S)
                    result = self._fetch_one(ticker)
                    by_id[ticker] = result
                    if result.fetch_fallback_reason == "rate_limited":
                        # The first individual 429 is enough to open the
                        # circuit. Do not continue issuing one request per
                        # remaining ticker.
                        for remaining in missing[index + 1:]:
                            by_id[remaining] = self._build_error_result(
                                remaining,
                                "yfinance rate-limit cooldown entered",
                                "rate_limit_cooldown",
                            )
                        break

        results = [by_id[ticker] for ticker in series_ids]
        if not any(
            result.fetch_fallback_reason in {"rate_limited", "rate_limit_cooldown"}
            for result in results
        ):
            self._clear_rate_limit_state()
        return results

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
        if self._cache:
            self._write_raw(ticker, frame.to_json(orient="records", date_format="iso"))
        return ProviderResult(
            provider=self.source_id,
            series_id=ticker,
            frame=frame,
            source_url=f"https://finance.yahoo.com/quote/{ticker}",
            source_params={"period": self._period},
            data_note=f"yfinance daily OHLCV for {self._tickers.get(ticker, ticker)}",
        )

    def _fetch_batch(self, series_ids: list[str]) -> dict[str, ProviderResult]:
        """One multi-ticker download — fewer Yahoo round-trips than N serial calls."""
        out: dict[str, ProviderResult] = {}
        try:
            import yfinance as yf
        except ImportError:
            for ticker in series_ids:
                out[ticker] = self._build_error_result(
                    ticker, "yfinance not installed", "missing_dependency"
                )
            return out

        try:
            # threads=False: launchd soft NOFILE is often ~256; threaded
            # Yahoo fetches open many sockets and trip EMFILE (errno 24).
            data = yf.download(
                series_ids,
                period=self._period,
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=False,
                timeout=self._timeout,
            )
        except Exception as exc:
            if self._is_rate_limit_error(exc):
                self._record_rate_limit(str(exc))
                logger.warning("ETF batch rate-limited; entering cooldown: %s", exc)
                return {
                    ticker: self._build_error_result(
                        ticker,
                        f"yfinance rate limited: {exc}",
                        "rate_limited",
                    )
                    for ticker in series_ids
                }
            logger.warning("ETF batch download failed: %s", exc)
            return out

        if data is None or data.empty:
            return out

        multi = isinstance(data.columns, pd.MultiIndex)
        for ticker in series_ids:
            try:
                if multi:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    ticker_df = data[ticker].dropna(how="all")
                else:
                    # Single-ticker response shape even when one id requested.
                    ticker_df = data
                if ticker_df.empty or "Close" not in ticker_df.columns:
                    continue
                frame = self._frame_from_ohlcv(ticker_df)
                if frame.empty:
                    continue
                out[ticker] = self._result_from_frame(ticker, frame)
            except Exception as exc:
                logger.warning("ETF batch parse failed for %s: %s", ticker, exc)
        return out

    def _fetch_one(self, ticker: str, *, attempts: int = _FETCH_ATTEMPTS) -> ProviderResult:
        try:
            import yfinance as yf
        except ImportError:
            return self._build_error_result(ticker, "yfinance not installed", "missing_dependency")

        last_error = f"yfinance returned no data for {ticker}"
        last_kind = "empty"
        for attempt in range(max(1, attempts)):
            try:
                data = yf.download(
                    ticker,
                    period=self._period,
                    progress=False,
                    auto_adjust=True,
                    timeout=self._timeout,
                )
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
                last_kind = "fetch_error"
                if self._is_rate_limit_error(exc):
                    self._record_rate_limit(str(exc))
                    last_error = f"yfinance rate limited: {exc}"
                    last_kind = "rate_limited"
                    return self._build_error_result(ticker, last_error, last_kind)

            if attempt + 1 < max(1, attempts):
                sleep_s = _RETRY_BASE_SLEEP_S * (2 ** attempt)
                logger.warning(
                    "ETF fetch retry %d/%d for %s after %s (sleep %.2fs)",
                    attempt + 1,
                    max(1, attempts),
                    ticker,
                    last_kind,
                    sleep_s,
                )
                time.sleep(sleep_s)

        return self._build_error_result(ticker, last_error, last_kind)

    def _rate_limit_state_path(self) -> Path:
        return self._raw_dir() / _RATE_LIMIT_STATE_FILE

    def _active_rate_limit_cooldown(self) -> float | None:
        if self._rate_limit_cooldown_s <= 0:
            return None
        try:
            payload = json.loads(self._rate_limit_state_path().read_text(encoding="utf-8"))
            recorded_at = datetime.fromisoformat(
                str(payload.get("recorded_at", "")).replace("Z", "+00:00")
            )
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=UTC)
            remaining = self._rate_limit_cooldown_s - (
                datetime.now(UTC) - recorded_at.astimezone(UTC)
            ).total_seconds()
            return remaining if remaining > 0 else None
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _record_rate_limit(self, error: str) -> None:
        if self._rate_limit_cooldown_s <= 0:
            return
        path = self._rate_limit_state_path()
        payload = {
            "provider": self.source_id,
            "reason": "rate_limited",
            "error": error[:500],
            "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "cooldown_seconds": self._rate_limit_cooldown_s,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            logger.debug("Could not persist yfinance rate-limit state", exc_info=True)

    def _clear_rate_limit_state(self) -> None:
        try:
            self._rate_limit_state_path().unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.debug("Could not clear yfinance rate-limit state", exc_info=True)

    @staticmethod
    def _is_rate_limit_error(error: BaseException) -> bool:
        text = f"{type(error).__name__}: {error}".lower()
        return any(
            marker in text
            for marker in (
                "ratelimit",
                "rate limit",
                "too many requests",
                "429",
            )
        )


__all__ = ["EtfYfinanceProvider", "DEFAULT_ETF_TICKERS"]
