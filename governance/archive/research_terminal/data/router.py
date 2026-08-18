"""
Hermes Data Router
Multi-source price data with primary → backup → validation fallback.

Data sources:
1. Tiingo (primary) - requires API key
2. FMP (backup) - requires API key
3. yfinance (fallback) - free, no key needed

Usage:
    from data.router import DataRouter
    router = DataRouter()
    df = router.get_ohlcv("GOOGL", start="2024-01-01")
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class DataRouter:
    """Multi-source price data router with fallback."""

    def __init__(self, cache_hours: int = 4):
        self.cache_hours = cache_hours
        self.sources_tried = []

    def get_ohlcv(
        self,
        symbol: str,
        start: str = "2024-01-01",
        end: Optional[str] = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Get OHLCV data with multi-source fallback.

        Args:
            symbol: Ticker symbol (e.g., "GOOGL", "SPY", "BTC-USD")
            start: Start date (YYYY-MM-DD)
            end: End date (YYYY-MM-DD), defaults to today
            interval: Data interval ("1d", "1h", etc.)

        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        if end is None:
            end = datetime.now().strftime("%Y-%m-%d")

        # Check cache first
        cached = self._check_cache(symbol, start, end, interval)
        if cached is not None:
            return cached

        # Try sources in order
        sources = [
            ("yfinance", self._fetch_yfinance),
            # Add more sources here when API keys available:
            # ("tiingo", self._fetch_tiingo),
            # ("fmp", self._fetch_fmp),
        ]

        errors = []
        for source_name, fetch_fn in sources:
            try:
                df = fetch_fn(symbol, start, end, interval)
                if df is not None and len(df) > 0:
                    df = self._normalize(df, symbol)
                    self._save_cache(symbol, start, end, interval, df)
                    return df
            except Exception as e:
                errors.append(f"{source_name}: {e}")
                self.sources_tried.append(source_name)

        raise RuntimeError(f"All data sources failed for {symbol}: {errors}")

    def _fetch_yfinance(
        self, symbol: str, start: str, end: str, interval: str
    ) -> pd.DataFrame:
        """Fetch from yfinance (fallback, free)."""
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end, interval=interval)

        if df.empty:
            raise ValueError(f"No data returned for {symbol}")

        # Rename columns
        df = df.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # Ensure date column
        if "date" not in df.columns and "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"})

        return df[["date", "open", "high", "low", "close", "volume"]]

    def _normalize(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Normalize DataFrame to standard format."""
        df = df.copy()

        # Ensure date is datetime
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        # Sort by date
        df = df.sort_values("date").reset_index(drop=True)

        # Add symbol column
        df["symbol"] = symbol

        # Calculate returns
        df["return_1d"] = df["close"].pct_change()
        df["return_5d"] = df["close"].pct_change(5)
        df["return_20d"] = df["close"].pct_change(20)
        df["return_60d"] = df["close"].pct_change(60)

        # Calculate moving averages
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma60"] = df["close"].rolling(60).mean()

        # Calculate volatility (20-day)
        df["volatility_20d"] = df["return_1d"].rolling(20).std() * (252 ** 0.5)

        # Calculate drawdown
        df["cummax"] = df["close"].cummax()
        df["drawdown"] = (df["close"] - df["cummax"]) / df["cummax"]

        # Calculate ATR (14-day)
        df["tr"] = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs()
        ], axis=1).max(axis=1)
        df["atr_14"] = df["tr"].rolling(14).mean()

        return df

    def _check_cache(
        self, symbol: str, start: str, end: str, interval: str
    ) -> Optional[pd.DataFrame]:
        """Check if cached data exists and is fresh."""
        cache_file = CACHE_DIR / f"{symbol}_{start}_{end}_{interval}.parquet"

        if cache_file.exists():
            # Check freshness
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if datetime.now() - mtime < timedelta(hours=self.cache_hours):
                try:
                    return pd.read_parquet(cache_file)
                except Exception:
                    logger.warning("Unable to read cached market data: %s", cache_file, exc_info=True)

        return None

    def _save_cache(
        self, symbol: str, start: str, end: str, interval: str, df: pd.DataFrame
    ):
        """Save data to cache."""
        cache_file = CACHE_DIR / f"{symbol}_{start}_{end}_{interval}.parquet"
        try:
            df.to_parquet(cache_file, index=False)
        except Exception:
            logger.warning("Unable to save optional market-data cache: %s", cache_file, exc_info=True)

    def get_info(self, symbol: str) -> dict:
        """Get ticker info (name, sector, etc.)."""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return {
                "symbol": symbol,
                "name": info.get("longName", symbol),
                "sector": info.get("sector", "N/A"),
                "industry": info.get("industry", "N/A"),
                "market_cap": info.get("marketCap", 0),
                "currency": info.get("currency", "USD"),
            }
        except Exception:
            return {"symbol": symbol, "name": symbol}


# Convenience function
def get_prices(symbol: str, start: str = "2024-01-01", end: str = None) -> pd.DataFrame:
    """Quick function to get price data."""
    router = DataRouter()
    return router.get_ohlcv(symbol, start, end)
