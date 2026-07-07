"""Portfolio benchmarks for stress-aware allocation backtests.

Implements P5 of the empirical roadmap:

  * Buy-and-hold S&P 500
  * Static 60/40 (monthly rebalance)
  * Risk parity (60-day inverse-vol weights, monthly rebalance)
  * Vol-target (target 10% annual vol on equity, cash for the rest)
  * Sigma-regime allocation (uses Sigma_t to pick equity weight)
  * Channel-aware allocation (uses M / D / K / X channels)
  * NFCI-regime allocation (control: same rule but with NFCI)

Inputs are minimal: a ``prices`` DataFrame with at least ``equity`` and
``bond`` columns (total-return indices) plus optional ``stress`` series.
Every strategy returns a tidy ``StrategyResult`` (equity curve + metrics).

The backtest is intentionally simple — daily forward-fill, daily returns,
monthly rebalance, no transaction costs. The point is comparison across
strategies on the same returns history, not a polished trading product.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


TRADING_DAYS = 252


@dataclass(frozen=True)
class StrategyResult:
    name: str
    weights: pd.DataFrame
    portfolio_returns: pd.Series
    equity_curve: pd.Series
    metrics: dict[str, float]
    notes: str = ""


@dataclass(frozen=True)
class StrategyComparison:
    results: tuple[StrategyResult, ...]

    def metrics_frame(self) -> pd.DataFrame:
        rows = [{"strategy": r.name, **r.metrics} for r in self.results]
        return pd.DataFrame(rows).set_index("strategy")

    def equity_curves(self) -> pd.DataFrame:
        return pd.concat(
            {r.name: r.equity_curve for r in self.results},
            axis=1,
        )


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    cleaned = prices.replace([np.inf, -np.inf], np.nan).ffill()
    return cleaned.pct_change().fillna(0.0)


def _portfolio_metrics(returns: pd.Series, regime: pd.Series | None = None) -> dict[str, float]:
    r = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if r.empty:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "annual_vol": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "hit_rate": 0.0,
        }
    equity = (1.0 + r).cumprod()
    n = len(r)
    annual_return = float(equity.iloc[-1] ** (TRADING_DAYS / max(n, 1)) - 1.0)
    annual_vol = float(r.std(ddof=0) * np.sqrt(TRADING_DAYS))
    sharpe = float(annual_return / annual_vol) if annual_vol > 0 else 0.0
    drawdown = (equity / equity.cummax() - 1.0)
    max_drawdown = float(drawdown.min())
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    hit = float((r > 0).mean())
    metrics = {
        "total_return": float(equity.iloc[-1] - 1.0),
        "annual_return": annual_return,
        "annual_vol": annual_vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "hit_rate": hit,
    }
    if regime is not None:
        regime_aligned = regime.reindex(r.index).ffill()
        for label in regime_aligned.dropna().unique():
            mask = regime_aligned == label
            if mask.sum() < 5:
                continue
            sub = r[mask]
            metrics[f"sharpe_{label}"] = float(
                sub.mean() / sub.std(ddof=0) * np.sqrt(TRADING_DAYS)
            ) if sub.std(ddof=0) > 0 else 0.0
            metrics[f"return_{label}"] = float((1.0 + sub).prod() - 1.0)
    return metrics


def _build_result(
    name: str,
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    regime: pd.Series | None = None,
    notes: str = "",
) -> StrategyResult:
    aligned_w = weights.reindex(returns.index).ffill().fillna(0.0)
    portfolio_r = (aligned_w.shift(1).fillna(0.0) * returns).sum(axis=1)
    equity = (1.0 + portfolio_r).cumprod()
    return StrategyResult(
        name=name,
        weights=aligned_w,
        portfolio_returns=portfolio_r,
        equity_curve=equity,
        metrics=_portfolio_metrics(portfolio_r, regime=regime),
        notes=notes,
    )


def _monthly_rebalance_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if len(idx) == 0:
        return idx
    months = pd.Series(idx, index=idx).groupby([idx.year, idx.month]).first()
    return pd.DatetimeIndex(months.values)


def buy_and_hold(prices: pd.DataFrame, asset: str = "equity", regime: pd.Series | None = None) -> StrategyResult:
    returns = daily_returns(prices)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    weights[asset] = 1.0
    return _build_result(f"buy_and_hold_{asset}", weights, returns, regime=regime,
                         notes="100% equity, no rebalance")


def static_sixty_forty(prices: pd.DataFrame, regime: pd.Series | None = None) -> StrategyResult:
    if not {"equity", "bond"}.issubset(prices.columns):
        raise ValueError("60/40 requires 'equity' and 'bond' columns")
    returns = daily_returns(prices)
    rebalances = _monthly_rebalance_index(prices.index)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    weights.loc[rebalances, "equity"] = 0.60
    weights.loc[rebalances, "bond"] = 0.40
    return _build_result("sixty_forty", weights, returns, regime=regime,
                         notes="60% equity / 40% bond, monthly rebalance")


def risk_parity(prices: pd.DataFrame, lookback: int = 60, regime: pd.Series | None = None) -> StrategyResult:
    if not {"equity", "bond"}.issubset(prices.columns):
        raise ValueError("risk parity requires 'equity' and 'bond' columns")
    returns = daily_returns(prices)
    vol = returns.rolling(lookback, min_periods=20).std()
    inv_vol = (1.0 / vol).replace([np.inf, -np.inf], np.nan)
    inv_vol = inv_vol[["equity", "bond"]].dropna(how="all")
    weights_full = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(0.0)
    rebal_idx = _monthly_rebalance_index(weights_full.index)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    weights.loc[rebal_idx, ["equity", "bond"]] = weights_full.reindex(rebal_idx).values
    return _build_result("risk_parity", weights, returns, regime=regime,
                         notes=f"Inverse-vol weights, {lookback}-day lookback, monthly rebalance")


def vol_target(
    prices: pd.DataFrame,
    target_annual_vol: float = 0.10,
    lookback: int = 60,
    asset: str = "equity",
    regime: pd.Series | None = None,
) -> StrategyResult:
    returns = daily_returns(prices)
    if asset not in returns.columns:
        raise ValueError(f"vol_target needs '{asset}' column")
    realized = returns[asset].rolling(lookback, min_periods=20).std() * np.sqrt(TRADING_DAYS)
    raw_w = (target_annual_vol / realized).clip(0.0, 1.5).fillna(0.0)
    rebal_idx = _monthly_rebalance_index(prices.index)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    weights.loc[rebal_idx, asset] = raw_w.reindex(rebal_idx).values
    return _build_result(
        f"vol_target_{int(target_annual_vol * 100)}",
        weights,
        returns,
        regime=regime,
        notes=f"Equity scaled to {target_annual_vol:.0%} annual vol, cash residual at zero return",
    )


@dataclass(frozen=True)
class RegimeAllocationRule:
    """Three-tier allocation keyed off a stress signal.

    The signal is z-scored on an expanding basis, so the thresholds are in
    z-units and stay comparable across signals (Sigma, NFCI, etc.).
    """
    low_threshold: float = 0.0
    high_threshold: float = 1.5
    weights_low: tuple[float, float] = (1.0, 0.0)
    weights_mid: tuple[float, float] = (0.6, 0.4)
    weights_high: tuple[float, float] = (0.3, 0.7)


def _expanding_zscore(series: pd.Series, min_periods: int = 60) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    mean = numeric.expanding(min_periods=min_periods).mean().shift(1)
    std = numeric.expanding(min_periods=min_periods).std().shift(1).replace(0.0, np.nan)
    return ((numeric - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def regime_allocation(
    prices: pd.DataFrame,
    stress_signal: pd.Series,
    rule: RegimeAllocationRule = RegimeAllocationRule(),
    name: str = "regime_alloc",
    regime: pd.Series | None = None,
) -> StrategyResult:
    if not {"equity", "bond"}.issubset(prices.columns):
        raise ValueError("regime allocation requires 'equity' and 'bond' columns")
    returns = daily_returns(prices)
    z = _expanding_zscore(stress_signal.reindex(prices.index).ffill())
    state = pd.Series("mid", index=prices.index)
    state.loc[z <= rule.low_threshold] = "low"
    state.loc[z >= rule.high_threshold] = "high"
    weight_map = {"low": rule.weights_low, "mid": rule.weights_mid, "high": rule.weights_high}
    rebal_idx = _monthly_rebalance_index(prices.index)
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    for ts in rebal_idx:
        eq, bd = weight_map[state.loc[ts]]
        weights.at[ts, "equity"] = eq
        weights.at[ts, "bond"] = bd
    return _build_result(name, weights, returns, regime=regime,
                         notes=f"Three-state regime alloc on {stress_signal.name or 'stress'}")


def channel_aware_allocation(
    prices: pd.DataFrame,
    channels: pd.DataFrame,
    sigma: pd.Series,
    rule: RegimeAllocationRule = RegimeAllocationRule(),
    regime: pd.Series | None = None,
) -> StrategyResult:
    """Channel-aware variant: same regime states as Sigma, but tilts the mid/high
    state weights based on which channel is leading.

    - K-led (curvature dominant): tilt away from equity, shrink mid by 0.10
    - X-led (shadow dominant): tilt away from credit (favor TLT over corp bond if available)
    - D-led (degrees-of-freedom dominant): keep mid/high but cap equity at 0.5
    - M-led: no extra tilt
    """
    base = regime_allocation(prices, sigma, rule=rule, name="channel_aware_base", regime=regime)
    if not {"M", "D", "K", "X"}.issubset(channels.columns):
        return StrategyResult(
            name="channel_aware",
            weights=base.weights,
            portfolio_returns=base.portfolio_returns,
            equity_curve=base.equity_curve,
            metrics=base.metrics,
            notes="Fallback: missing channel columns, behaves like regime_alloc",
        )

    abs_channels = channels.copy()
    abs_channels["D"] = -channels["D"]
    leading = abs_channels[["M", "D", "K", "X"]].idxmax(axis=1).reindex(prices.index).ffill()

    weights = base.weights.copy()
    rebal_idx = _monthly_rebalance_index(prices.index)
    for ts in rebal_idx:
        if ts not in weights.index:
            continue
        chan = leading.get(ts, "M")
        eq = float(weights.at[ts, "equity"])
        bd = float(weights.at[ts, "bond"])
        if chan == "K" and eq > 0.3:
            shift = 0.10
            eq = max(0.0, eq - shift)
            bd = min(1.0, bd + shift)
        elif chan == "D" and eq > 0.5:
            shift = eq - 0.5
            eq = 0.5
            bd = min(1.0, bd + shift)
        elif chan == "X" and eq > 0.4:
            shift = 0.05
            eq = max(0.0, eq - shift)
            bd = min(1.0, bd + shift)
        weights.at[ts, "equity"] = eq
        weights.at[ts, "bond"] = bd

    returns = daily_returns(prices)
    return _build_result("channel_aware", weights, returns, regime=regime,
                         notes="Sigma regime + leading-channel tilt (K shrinks equity, D caps it, X tilts to bonds)")


def nfci_regime_allocation(
    prices: pd.DataFrame,
    nfci: pd.Series,
    rule: RegimeAllocationRule | None = None,
    regime: pd.Series | None = None,
) -> StrategyResult:
    """Control strategy: same allocation rule but driven by NFCI instead of Sigma."""
    rule = rule or RegimeAllocationRule()
    return regime_allocation(prices, nfci.rename("NFCI"), rule=rule, name="nfci_regime", regime=regime)


def run_strategy_panel(
    prices: pd.DataFrame,
    sigma: pd.Series,
    channels: pd.DataFrame | None = None,
    extra_signals: Mapping[str, pd.Series] | None = None,
    regime: pd.Series | None = None,
) -> StrategyComparison:
    """Run the full panel of strategies and return a comparison object.

    `extra_signals` lets the caller add control allocators (e.g. NFCI, KCFSI)
    to verify whether Sigma-driven allocation has incremental value over
    other public stress indices.
    """
    results: list[StrategyResult] = []
    results.append(buy_and_hold(prices, regime=regime))
    results.append(static_sixty_forty(prices, regime=regime))
    results.append(risk_parity(prices, regime=regime))
    results.append(vol_target(prices, regime=regime))
    results.append(regime_allocation(prices, sigma.rename("SIGMA"), name="sigma_regime", regime=regime))
    if channels is not None:
        results.append(channel_aware_allocation(prices, channels, sigma, regime=regime))
    if extra_signals:
        for name, series in extra_signals.items():
            results.append(
                regime_allocation(prices, series.rename(name), name=f"{name}_regime", regime=regime)
            )
    return StrategyComparison(results=tuple(results))


def head_to_head(comparison: StrategyComparison, baseline: str = "sixty_forty") -> pd.DataFrame:
    """Pivot a comparison into a delta-vs-baseline table on the key metrics."""
    metrics = comparison.metrics_frame()
    if baseline not in metrics.index:
        raise KeyError(f"Baseline {baseline} not in comparison")
    deltas = metrics.subtract(metrics.loc[baseline], axis=1)
    deltas.index = [f"{idx} - {baseline}" if idx != baseline else baseline for idx in deltas.index]
    return deltas


__all__ = [
    "RegimeAllocationRule",
    "StrategyComparison",
    "StrategyResult",
    "TRADING_DAYS",
    "buy_and_hold",
    "channel_aware_allocation",
    "daily_returns",
    "head_to_head",
    "nfci_regime_allocation",
    "regime_allocation",
    "risk_parity",
    "run_strategy_panel",
    "static_sixty_forty",
    "vol_target",
]
