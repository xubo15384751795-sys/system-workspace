"""Backtest engine — compute performance metrics and comparison reports.

Metrics:
  - Total return, annualized return
  - Annualized volatility
  - Sharpe ratio (rf=0)
  - Max drawdown, max drawdown duration
  - Calmar ratio (ann return / max drawdown)
  - Win rate (% of positive days)
  - Avg win / avg loss
  - Time in market (% of days with non-zero position)
  - Tail loss: worst 5% of daily returns
  - Number of trades (position changes)

Comparison: baseline vs baseline + System overlay.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class PerformanceMetrics:
    """Summary performance statistics for a strategy."""
    name: str
    total_return: float = 0.0
    ann_return: float = 0.0
    ann_volatility: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    max_dd_duration_days: int = 0
    calmar: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    time_in_market: float = 0.0
    tail_loss_5pct: float = 0.0
    n_trades: int = 0
    n_days: int = 0
    start_date: str = ""
    end_date: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total_return": float(round(self.total_return, 4)),
            "ann_return": float(round(self.ann_return, 4)),
            "ann_volatility": float(round(self.ann_volatility, 4)),
            "sharpe": float(round(self.sharpe, 3)),
            "max_drawdown": float(round(self.max_drawdown, 4)),
            "max_dd_duration_days": int(self.max_dd_duration_days),
            "calmar": float(round(self.calmar, 3)),
            "win_rate": float(round(self.win_rate, 4)),
            "avg_win": float(round(self.avg_win, 6)),
            "avg_loss": float(round(self.avg_loss, 6)),
            "time_in_market": float(round(self.time_in_market, 4)),
            "tail_loss_5pct": float(round(self.tail_loss_5pct, 6)),
            "n_trades": int(self.n_trades),
            "n_days": int(self.n_days),
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


def compute_drawdown_series(equity: pd.Series) -> pd.Series:
    """Compute drawdown series from an equity curve."""
    peak = equity.cummax()
    return (equity - peak) / peak


def compute_max_dd_duration(drawdown: pd.Series) -> int:
    """Compute maximum drawdown duration in trading days."""
    in_dd = drawdown < 0
    if not in_dd.any():
        return 0
    # Count consecutive drawdown periods
    groups = (~in_dd).cumsum()
    dd_groups = in_dd.groupby(groups).sum()
    return int(dd_groups.max())


def compute_metrics(
    daily_returns: pd.Series,
    position: pd.Series,
    name: str = "strategy",
) -> PerformanceMetrics:
    """Compute full performance metrics for a strategy.

    Args:
        daily_returns: strategy daily returns (already position-weighted).
        position: daily position series (for trade counting).
        name: label for this strategy.
    """
    m = PerformanceMetrics(name=name)

    if len(daily_returns) == 0:
        return m

    m.n_days = len(daily_returns)
    m.start_date = str(daily_returns.index[0].date())
    m.end_date = str(daily_returns.index[-1].date())

    # Equity curve
    equity = (1 + daily_returns).cumprod()
    m.total_return = equity.iloc[-1] - 1.0

    # Annualized return
    years = m.n_days / TRADING_DAYS_PER_YEAR
    if years > 0 and equity.iloc[-1] > 0:
        m.ann_return = equity.iloc[-1] ** (1 / years) - 1.0

    # Annualized volatility
    m.ann_volatility = daily_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Sharpe ratio (rf=0)
    if m.ann_volatility > 0:
        m.sharpe = m.ann_return / m.ann_volatility

    # Drawdown
    dd = compute_drawdown_series(equity)
    m.max_drawdown = dd.min()
    m.max_dd_duration_days = compute_max_dd_duration(dd)

    # Calmar ratio
    if m.max_drawdown < 0:
        m.calmar = m.ann_return / abs(m.max_drawdown)

    # Win rate
    trading_days = daily_returns[daily_returns != 0]
    if len(trading_days) > 0:
        m.win_rate = (trading_days > 0).mean()
        wins = trading_days[trading_days > 0]
        losses = trading_days[trading_days < 0]
        m.avg_win = wins.mean() if len(wins) > 0 else 0.0
        m.avg_loss = losses.mean() if len(losses) > 0 else 0.0

    # Time in market
    m.time_in_market = (position != 0).mean()

    # Tail loss: average of worst 5% of daily returns
    n_tail = max(1, int(len(daily_returns) * 0.05))
    m.tail_loss_5pct = daily_returns.nsmallest(n_tail).mean()

    # Trade count: number of position changes
    pos_changes = position.diff().fillna(0)
    m.n_trades = int((pos_changes != 0).sum())

    return m


def run_comparison(
    daily_returns: pd.Series,
    baseline_position: pd.Series,
    overlay_position: pd.Series,
) -> dict:
    """Run full comparison between baseline and System overlay.

    Returns dict with:
        baseline: PerformanceMetrics
        overlay: PerformanceMetrics
        comparison: dict of deltas
        yearly: per-year comparison table
    """
    baseline_ret = daily_returns * baseline_position.shift(1).fillna(0)
    overlay_ret = daily_returns * overlay_position.shift(1).fillna(0)

    baseline_m = compute_metrics(baseline_ret, baseline_position, "baseline")
    overlay_m = compute_metrics(overlay_ret, overlay_position, "overlay")

    # Comparison deltas
    comparison = {
        "return_delta": float(overlay_m.total_return - baseline_m.total_return),
        "sharpe_delta": float(overlay_m.sharpe - baseline_m.sharpe),
        "max_dd_delta": float(overlay_m.max_drawdown - baseline_m.max_drawdown),
        "calmar_delta": float(overlay_m.calmar - baseline_m.calmar),
        "tail_loss_delta": float(overlay_m.tail_loss_5pct - baseline_m.tail_loss_5pct),
        "trades_delta": int(overlay_m.n_trades - baseline_m.n_trades),
    }

    # Yearly breakdown
    yearly = _yearly_comparison(daily_returns, baseline_position, overlay_position)

    return {
        "baseline": baseline_m.to_dict(),
        "overlay": overlay_m.to_dict(),
        "comparison": {k: round(v, 4) for k, v in comparison.items()},
        "yearly": yearly,
    }


def _yearly_comparison(
    daily_returns: pd.Series,
    baseline_position: pd.Series,
    overlay_position: pd.Series,
) -> list[dict]:
    """Compute per-year comparison between baseline and overlay."""
    baseline_ret = daily_returns * baseline_position.shift(1).fillna(0)
    overlay_ret = daily_returns * overlay_position.shift(1).fillna(0)

    years = sorted(set(daily_returns.index.year))
    rows = []
    for year in years:
        mask = daily_returns.index.year == year
        if mask.sum() < 20:
            continue

        b_year = baseline_ret[mask]
        o_year = overlay_ret[mask]
        b_eq = (1 + b_year).cumprod()
        o_eq = (1 + o_year).cumprod()

        b_dd = compute_drawdown_series(b_eq)
        o_dd = compute_drawdown_series(o_eq)

        rows.append({
            "year": int(year),
            "baseline_return": float(round(b_eq.iloc[-1] - 1, 4)),
            "overlay_return": float(round(o_eq.iloc[-1] - 1, 4)),
            "return_delta": float(round(o_eq.iloc[-1] - b_eq.iloc[-1], 4)),
            "baseline_max_dd": float(round(b_dd.min(), 4)),
            "overlay_max_dd": float(round(o_dd.min(), 4)),
            "dd_improvement": float(round(o_dd.min() - b_dd.min(), 4)),
            "baseline_days_in_market": int((baseline_position[mask] != 0).sum()),
            "overlay_days_in_market": int((overlay_position[mask] != 0).sum()),
        })
    return rows
