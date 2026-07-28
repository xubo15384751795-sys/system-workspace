"""ETF price provider via yfinance.

Acquires daily OHLCV data for ETF tickers.  This is the Harvester path
for ETF data — root scripts must not call yfinance directly.

Usage:
    provider = EtfYfinanceProvider()
    results = provider.fetch_series(["SPY", "HYG", "TLT"])
"""
from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

# Yahoo rate-limits bursty sequential downloads; brief spacing + retries
# recover from the empty-frame / transient-error pattern seen in daily runs.
_FETCH_ATTEMPTS = 3
_RETRY_BASE_SLEEP_S = 0.75
_INTER_TICKER_SLEEP_S = 0.2

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

    def fetch_series(self, series_ids: list[str] | None = None) -> list[ProviderResult]:
        if series_ids is None:
            series_ids = list(self._tickers.keys())
        if not series_ids:
            return []

        by_id = self._fetch_batch(series_ids)
        missing = [ticker for ticker in series_ids if by_id.get(ticker) is None or by_id[ticker].empty()]
        if missing:
            # Detect rate-limiting: if batch returned nothing, Yahoo is likely
            # rate-limiting. Don't hammer with 34 serial retries (each 30s timeout).
            if not by_id or all(r.frame is None or r.frame.empty for r in by_id.values()):
                logger.warning(
                    "ETF batch returned no data for %d tickers; skipping serial retries "
                    "(likely Yahoo rate-limit)", len(missing),
                )
                for ticker in missing:
                    by_id[ticker] = self._build_error_result(
                        ticker, "yfinance rate-limited (batch empty)", "rate_limited"
                    )
            else:
                logger.warning("ETF batch incomplete; retrying %d tickers individually", len(missing))
                for index, ticker in enumerate(missing):
                    if index:
                        time.sleep(_INTER_TICKER_SLEEP_S)
                    by_id[ticker] = self._fetch_one(ticker)

        return [by_id[ticker] for ticker in series_ids]

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
            )
        except Exception as exc:
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
                last_kind = "fetch_error"

            if attempt + 1 < _FETCH_ATTEMPTS:
                sleep_s = _RETRY_BASE_SLEEP_S * (2 ** attempt)
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
