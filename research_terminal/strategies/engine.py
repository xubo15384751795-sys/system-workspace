"""
Quick Backtest Strategies
Simple strategies for fast evaluation.

Usage:
    from strategies.engine import QuickBacktest
    bt = QuickBacktest(df, benchmark_df)
    results = bt.run_all()
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class BacktestResult:
    """Single strategy backtest result."""
    name: str
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    best_trade: float
    worst_trade: float
    excess_return: float
    equity_curve: pd.Series
    trades: pd.DataFrame


class QuickBacktest:
    """Run quick backtests on price data."""

    def __init__(self, df: pd.DataFrame, benchmark_df: Optional[pd.DataFrame] = None):
        """
        Args:
            df: OHLCV DataFrame with columns: date, open, high, low, close, volume
            benchmark_df: Benchmark OHLCV DataFrame (optional)
        """
        self.df = df.copy()
        self.benchmark_df = benchmark_df
        self.results = {}

    def run_all(self) -> Dict[str, BacktestResult]:
        """Run all strategies."""
        strategies = {
            "buy_and_hold": self.buy_and_hold,
            "ma_cross_20_60": self.ma_cross_20_60,
            "momentum_20d": self.momentum_20d,
            "mean_reversion_20d": self.mean_reversion_20d,
        }

        for name, strategy_fn in strategies.items():
            try:
                self.results[name] = strategy_fn()
            except Exception as e:
                print(f"Strategy {name} failed: {e}")

        return self.results

    def buy_and_hold(self) -> BacktestResult:
        """Simple buy and hold strategy."""
        df = self.df.copy()
        df["position"] = 1.0  # Always long
        df["strategy_return"] = df["position"] * df["return_1d"]
        df["equity"] = (1 + df["strategy_return"]).cumprod()

        return self._calculate_metrics(df, "Buy & Hold")

    def ma_cross_20_60(self) -> BacktestResult:
        """MA20/MA60 crossover strategy."""
        df = self.df.copy()

        # Generate signals
        df["signal"] = 0
        df.loc[df["ma20"] > df["ma60"], "signal"] = 1  # Long
        df.loc[df["ma20"] < df["ma60"], "signal"] = -1  # Short (or flat)

        # Use signal as position (shifted to avoid look-ahead)
        df["position"] = df["signal"].shift(1)
        df["position"] = df["position"].fillna(0)

        # Calculate returns
        df["strategy_return"] = df["position"] * df["return_1d"]
        df["equity"] = (1 + df["strategy_return"]).cumprod()

        return self._calculate_metrics(df, "MA Cross 20/60")

    def momentum_20d(self) -> BacktestResult:
        """20-day momentum strategy."""
        df = self.df.copy()

        # Signal: long if 20-day return > 0
        df["signal"] = 0
        df.loc[df["return_20d"] > 0, "signal"] = 1
        df.loc[df["return_20d"] < -0.05, "signal"] = -1  # Short on strong down

        df["position"] = df["signal"].shift(1)
        df["position"] = df["position"].fillna(0)

        df["strategy_return"] = df["position"] * df["return_1d"]
        df["equity"] = (1 + df["strategy_return"]).cumprod()

        return self._calculate_metrics(df, "Momentum 20D")

    def mean_reversion_20d(self) -> BacktestResult:
        """20-day mean reversion strategy."""
        df = self.df.copy()

        # Signal: long if price < MA20, short if price > MA20
        df["signal"] = 0
        df.loc[df["close"] < df["ma20"] * 0.98, "signal"] = 1  # Buy dip
        df.loc[df["close"] > df["ma20"] * 1.02, "signal"] = -1  # Sell rip

        df["position"] = df["signal"].shift(1)
        df["position"] = df["position"].fillna(0)

        df["strategy_return"] = df["position"] * df["return_1d"]
        df["equity"] = (1 + df["strategy_return"]).cumprod()

        return self._calculate_metrics(df, "Mean Reversion 20D")

    def _calculate_metrics(self, df: pd.DataFrame, name: str) -> BacktestResult:
        """Calculate performance metrics."""
        # Remove NaN
        df = df.dropna(subset=["strategy_return", "equity"])

        if len(df) < 2:
            raise ValueError("Not enough data for backtest")

        # Total return
        total_return = df["equity"].iloc[-1] / df["equity"].iloc[0] - 1

        # Annual return
        days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
        years = days / 365.25
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # Max drawdown
        cummax = df["equity"].cummax()
        drawdown = (df["equity"] - cummax) / cummax
        max_drawdown = drawdown.min()

        # Sharpe ratio (annualized)
        daily_returns = df["strategy_return"]
        sharpe = (daily_returns.mean() / daily_returns.std()) * (252 ** 0.5) if daily_returns.std() > 0 else 0

        # Win rate
        winning_days = (daily_returns > 0).sum()
        total_days = (daily_returns != 0).sum()
        win_rate = winning_days / total_days if total_days > 0 else 0

        # Trade count (position changes)
        position_changes = df["position"].diff().abs()
        total_trades = int(position_changes.sum() / 2)  # Divide by 2 for entry+exit

        # Best/worst trade
        best_trade = daily_returns.max()
        worst_trade = daily_returns.min()

        # Excess return vs benchmark
        excess_return = 0
        if self.benchmark_df is not None:
            benchmark_return = self.benchmark_df["close"].iloc[-1] / self.benchmark_df["close"].iloc[0] - 1
            excess_return = total_return - benchmark_return

        return BacktestResult(
            name=name,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=win_rate,
            total_trades=total_trades,
            best_trade=best_trade,
            worst_trade=worst_trade,
            excess_return=excess_return,
            equity_curve=df.set_index("date")["equity"],
            trades=df[["date", "close", "position", "strategy_return"]].copy()
        )
