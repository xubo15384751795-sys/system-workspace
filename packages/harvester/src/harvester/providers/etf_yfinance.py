"""ETF price provider via yfinance.

Acquires daily OHLCV data for ETF tickers.  This is the Harvester path
for ETF data — root scripts must not call yfinance directly.

Usage:
    provider = EtfYfinanceProvider()
    results = provider.fetch_series(["SPY", "HYG", "TLT"])
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

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
        return [self._fetch_one(ticker) for ticker in series_ids]

    def _fetch_one(self, ticker: str) -> ProviderResult:
        try:
            import yfinance as yf
        except ImportError:
            return self._build_error_result(ticker, "yfinance not installed", "missing_dependency")

        try:
            data = yf.download(ticker, period=self._period, progress=False, auto_adjust=True)
            if data.empty:
                return self._build_error_result(ticker, f"yfinance returned no data for {ticker}", "empty")

            # Normalize columns — yfinance may return MultiIndex for single ticker
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            frame = pd.DataFrame({
                "date": data.index,
                "value": data["Close"].values,
                "open": data["Open"].values,
                "high": data["High"].values,
                "low": data["Low"].values,
                "volume": data["Volume"].values,
                "unit": "USD",
                "frequency": "daily",
            })
            frame = frame.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

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
        except Exception as exc:
            return self._build_error_result(ticker, f"yfinance error: {exc}", "fetch_error")


__all__ = ["EtfYfinanceProvider", "DEFAULT_ETF_TICKERS"]
